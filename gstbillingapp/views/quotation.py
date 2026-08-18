# Django imports
from django.contrib import messages
from django.db.models import Max
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.urls import reverse

# Models
from ..models import Customer, Quotation, Invoice, UserProfile, Product, ProductCategory

# Utility functions
from ..utils import (
    invoice_data_validator,
    invoice_data_processor,
    update_products_from_invoice,
    update_inventory,
    auto_deduct_book_from_invoice,
    build_quotation_item,
    resolve_cart_context,
    cart_product_payload,
    find_matching_customer,
    CartAccessError
)

# Third-party libraries
import json
import datetime
import num2words


# ================= Quotation CRUD =============================

@login_required
def quotation_create(request):
    """Create a new quotation (draft invoice)"""
    user_profile = get_object_or_404(UserProfile, user=request.user)
    
    # Validate business info
    if not user_profile.business_title:
        messages.warning(request, "Please update your business name before creating quotations.")
        return redirect('user_profile_edit')
    if not user_profile.business_gst:
        messages.warning(request, "Please update your business GST number before creating quotations.")
        return redirect('user_profile_edit')

    context = {}
    
    # Get next quotation numbers
    context['non_gst_quotation_number'] = Quotation.objects.filter(
        user=request.user, is_gst=False
    ).aggregate(Max('quotation_number'))['quotation_number__max']
    if not context['non_gst_quotation_number']:
        context['non_gst_quotation_number'] = 1
    else:
        context['non_gst_quotation_number'] += 1

    # GST quotation numbers (shared across same GST)
    max_quotation_number = []
    user_profiles = UserProfile.objects.filter(business_gst=user_profile.business_gst)
    for profile in user_profiles:
        max_num = Quotation.objects.filter(
            user=profile.user, is_gst=True
        ).aggregate(Max('quotation_number'))['quotation_number__max']
        max_quotation_number.append(max_num)
    max_quotation_number = [num for num in max_quotation_number if num is not None]

    if max_quotation_number:
        context['default_quotation_number'] = max(max_quotation_number) + 1
    else:
        context['default_quotation_number'] = 1

    # Add template-compatible variable names
    context['default_invoice_number'] = context['default_quotation_number']
    context['non_gst_invoice_number'] = context['non_gst_quotation_number']
    context['default_invoice_date'] = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')
    
    # Calculate default valid until date (30 days from now)
    valid_until = datetime.datetime.now() + datetime.timedelta(days=30)
    context['default_valid_until'] = valid_until.strftime('%Y-%m-%d')

    if request.method == 'POST':
        quotation_data = request.POST
        
        # Check if non-GST
        non_gst_mode = 'nongstcheck' in quotation_data
        is_gst = not non_gst_mode
        
        # A GST quotation needs the customer's GSTIN. Rather than rejecting, fall back to
        # a non-GST quotation — but the number submitted with the form came from the GST
        # series, so it has to be re-drawn from the non-GST series below.
        auto_downgraded_to_non_gst = False
        if is_gst and quotation_data['customer-gst'].strip() == '':
            is_gst = False
            auto_downgraded_to_non_gst = True
            messages.info(
                request,
                "Customer has no GST Number — this was created as a NON-GST quotation."
            )
        
        # Validate data (reuse invoice validator)
        validation_error = invoice_data_validator(quotation_data)
        if validation_error:
            context["error_message"] = validation_error
            return render(request, 'quotations/quotation_create.html', context)

        # Process data (reuse invoice processor)
        quotation_data_processed = invoice_data_processor(quotation_data)
        
        # Check if modify customer details is enabled
        is_modified_customer = len(request.POST.getlist('modify-customer-details')) > 0
        
        # Get or create customer
        customer = None
        
        if is_modified_customer:
            # When modifying details, still need to find/create a base customer.
            # Match on the normalised name so we reuse the existing record instead of
            # creating a near-duplicate that differs only in casing.
            customer = find_matching_customer(request.user, quotation_data)

            if not customer:
                # Create a base customer record with the provided details
                customer = Customer.objects.create(
                    user=request.user,
                    customer_name=quotation_data['customer-name'],
                    customer_address=quotation_data['customer-address'],
                    customer_phone=quotation_data['customer-phone'],
                    customer_gst=quotation_data['customer-gst']
                )
                messages.info(request, f"New customer '{customer.customer_name}' created.")
        else:
            # Normal flow - match an existing customer by name (+ phone).
            customer = find_matching_customer(request.user, quotation_data)

            if not customer:
                # Redirect to customer add page
                messages.warning(request, "Please add the customer first before creating a quotation.")
                return redirect('customer_add')

        # Update products (optional for quotations, but keeps catalog current)
        # update_products_from_invoice(quotation_data_processed, request)

        # Save quotation
        quotation_data_processed_json = json.dumps(quotation_data_processed)
        
        # Get valid_until date
        valid_until_date = quotation_data.get('valid-until', '')
        if valid_until_date:
            valid_until_date = datetime.datetime.strptime(valid_until_date, '%Y-%m-%d').date()
        else:
            valid_until_date = None
        
        quotation_number = int(quotation_data['invoice-number'])  # Reusing form field name
        if auto_downgraded_to_non_gst:
            # The posted number belongs to the GST series; take the next non-GST one.
            max_non_gst = Quotation.objects.filter(
                user=request.user, is_gst=False
            ).aggregate(Max('quotation_number'))['quotation_number__max']
            quotation_number = (max_non_gst or 0) + 1

        new_quotation = Quotation(
            user=request.user,
            quotation_number=quotation_number,
            quotation_date=datetime.datetime.strptime(quotation_data['invoice-date'], '%Y-%m-%d'),
            valid_until=valid_until_date,
            quotation_customer=customer,
            quotation_json=quotation_data_processed_json,
            is_gst=is_gst,
            status='DRAFT',
            created_by_customer=False,
            customer_details_modified=is_modified_customer
        )
        new_quotation.save()

        messages.success(request, f'Quotation #{new_quotation.quotation_number} created successfully')
        return redirect('quotation_viewer', quotation_id=new_quotation.id)

    return render(request, 'quotations/quotation_create.html', context)


@login_required
def quotations(request):
    """List all quotations with server-side DataTables"""
    context = {}
    # Get all customers for dropdown filter
    customers = Customer.objects.filter(user=request.user).order_by('customer_name')
    context['customers'] = customers
    return render(request, 'quotations/quotations.html', context)


@login_required
def quotations_ajax(request):
    """AJAX endpoint for server-side DataTables processing"""
    from datetime import timedelta
    from django.utils import timezone
    from django.db.models import Q
    
    try:
        draw = int(request.GET.get('draw', 1))
        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 15))
        search_value = request.GET.get('search[value]', '')
        order_column_index = int(request.GET.get('order[0][column]', 0))
        order_direction = request.GET.get('order[0][dir]', 'desc')
        
        # Filter parameters
        quotation_type = request.GET.get('quotation_type', 'all')  # all, gst, non_gst
        status_filter = request.GET.get('status_filter', 'all')  # all, draft, approved, converted
        date_filter = request.GET.get('date_filter', 'all')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        customer_id = request.GET.get('customer_id', '')
        
        # Base queryset
        queryset = Quotation.objects.filter(user=request.user).select_related('quotation_customer')
        
        # Apply customer filter
        if customer_id and customer_id.isdigit():
            queryset = queryset.filter(quotation_customer__id=int(customer_id))
        
        # Apply type filter
        if quotation_type == 'gst':
            queryset = queryset.filter(is_gst=True)
        elif quotation_type == 'non_gst':
            queryset = queryset.filter(is_gst=False)
        
        # Apply status filter
        if status_filter == 'draft':
            queryset = queryset.filter(status='DRAFT')
        elif status_filter == 'approved':
            queryset = queryset.filter(status='APPROVED')
        elif status_filter == 'processing':
            queryset = queryset.filter(status='PROCESSING')
        elif status_filter == 'packed':
            queryset = queryset.filter(status='PACKED')
        elif status_filter == 'shipped':
            queryset = queryset.filter(status='SHIPPED')
        elif status_filter == 'out_for_delivery':
            queryset = queryset.filter(status='OUT_FOR_DELIVERY')
        elif status_filter == 'delivered':
            queryset = queryset.filter(status='DELIVERED')
        elif status_filter == 'converted':
            queryset = queryset.filter(status='CONVERTED')
        
        # Apply date filters
        if date_filter and date_filter != 'all':
            if date_filter == 'today':
                today = timezone.now().date()
                queryset = queryset.filter(quotation_date=today)
            elif date_filter == 'week':
                week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
                queryset = queryset.filter(quotation_date__gte=week_start)
            elif date_filter == 'month':
                month_start = timezone.now().date().replace(day=1)
                queryset = queryset.filter(quotation_date__gte=month_start)
            elif date_filter == 'custom' and start_date and end_date:
                try:
                    queryset = queryset.filter(quotation_date__gte=start_date, quotation_date__lte=end_date)
                except:
                    pass
        
        # Apply search filter
        if search_value:
            queryset = queryset.filter(
                Q(quotation_number__icontains=search_value) |
                Q(quotation_customer__customer_name__icontains=search_value)
            )
        
        # Total records
        total_records = Quotation.objects.filter(user=request.user).count()
        
        # Filtered records count
        filtered_records = queryset.count()
        
        # Ordering
        order_columns = ['quotation_number', 'quotation_date', 'quotation_customer__customer_name', 'status']
        if 0 <= order_column_index < len(order_columns):
            order_by = order_columns[order_column_index]
            if order_direction == 'desc':
                order_by = '-' + order_by
            queryset = queryset.order_by(order_by)
        else:
            queryset = queryset.order_by('-id')
        
        # Calculate total amount
        total_quotation_amount = 0.0
        quotation_jsons = queryset.values_list('quotation_json', flat=True)
        for quotation_json_str in quotation_jsons:
            try:
                quotation_json = json.loads(quotation_json_str)
                quotation_amount = float(quotation_json.get('invoice_total_amt_with_gst', 0))
                total_quotation_amount += quotation_amount
            except Exception:
                pass
        
        # Pagination
        queryset = queryset[start:start + length]
        
        # Prepare data
        data = []
        for quotation in queryset:
            # Quotation number
            if quotation.is_gst:
                quotation_num = f'QT-{quotation.quotation_number}'
            else:
                quotation_num = f'<span class="text-danger font-weight-bold">QT-NG{quotation.quotation_number}</span>'

            # Flag quotations that came in through the Quotation Cart.
            if quotation.created_from_cart:
                quotation_num += ' <span class="badge badge-info" title="Created from Quotation Cart"><i class="fas fa-shopping-basket"></i> Cart</span>'

            # Customer
            if quotation.quotation_customer:
                customer_html = f'<a href="/customer/edit/{quotation.quotation_customer.id}" style="text-decoration: none;color: black;">{quotation.quotation_customer.customer_name}</a>'
            else:
                customer_html = '<span class="text-danger">N/A</span>'

            # Quotation Amount
            try:
                quotation_json = json.loads(quotation.quotation_json)
                quotation_amount = float(quotation_json.get('invoice_total_amt_with_gst', 0))
            except Exception:
                quotation_amount = 0.0

            # Status badge
            status_badges = {
                'DRAFT': '<span class="badge badge-secondary">Draft</span>',
                'APPROVED': '<span class="badge badge-success">Approved</span>',
                'PROCESSING': '<span class="badge badge-info"><i class="fas fa-cog fa-spin"></i> Processing</span>',
                'PACKED': '<span class="badge badge-primary"><i class="fas fa-box"></i> Packed</span>',
                'SHIPPED': '<span class="badge badge-primary"><i class="fas fa-shipping-fast"></i> Shipped</span>',
                'OUT_FOR_DELIVERY': '<span class="badge badge-info"><i class="fas fa-truck"></i> Out for Delivery</span>',
                'DELIVERED': '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Delivered</span>',
                'CONVERTED': '<span class="badge badge-dark"><i class="fas fa-check-double"></i> Received</span>'
            }
            status_html = status_badges.get(quotation.status, quotation.status)

            # Actions
            actions_html = '<div class="btn-group" role="group">'
            actions_html += f'<a href="/quotation/{quotation.id}" class="btn btn-primary btn-sm btn-curve" title="View"><i class="fa fa-eye"></i></a>'
            
            if quotation.can_be_edited():
                actions_html += f'<a href="/quotation/edit/{quotation.id}" class="btn btn-warning btn-sm btn-curve" title="Edit"><i class="fa fa-edit"></i></a>'
            
            if quotation.can_be_converted():
                actions_html += f'<button type="button" onclick="convertToInvoice({quotation.id})" class="btn btn-success btn-sm btn-curve" title="Convert to Invoice"><i class="fa fa-exchange"></i></button>'
            
            if quotation.converted_invoice:
                actions_html += f'<a href="/invoice/{quotation.converted_invoice.id}" class="btn btn-info btn-sm btn-curve" title="View Invoice"><i class="fa fa-file-invoice"></i></a>'
            
            if quotation.can_be_edited():
                actions_html += f'<button type="button" class="btn btn-danger btn-sm btn-curve" onclick="deleteQuotation({quotation.id})" title="Delete"><i class="fa fa-trash"></i></button>'
            
            actions_html += '</div>'

            data.append({
                'quotation_number': quotation_num,
                'quotation_date': quotation.quotation_date.strftime('%b %d, %Y'),
                'customer': customer_html,
                'quotation_amount': f"₹ {quotation_amount:,.2f}",
                'status': status_html,
                'actions': actions_html
            })

        return JsonResponse({
            'draw': draw,
            'recordsTotal': total_records,
            'recordsFiltered': filtered_records,
            'data': data,
            'total_quotation_amount': total_quotation_amount
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in quotations_ajax: {error_details}")
        return JsonResponse({
            'error': str(e),
            'details': error_details
        }, status=500)


@login_required
def quotation_viewer(request, quotation_id):
    """View quotation details"""
    quotation_obj = get_object_or_404(Quotation, user=request.user, id=quotation_id)
    user_profile = get_object_or_404(UserProfile, user=request.user)

    context = {}
    context['quotation'] = quotation_obj
    context['quotation_data'] = json.loads(quotation_obj.quotation_json)
    context['currency'] = "₹"
    context['total_in_words'] = num2words.num2words(
        int(context['quotation_data']['invoice_total_amt_with_gst']), 
        lang='en_IN'
    ).title()
    context['user_profile'] = user_profile
    context['nav_hide'] = request.GET.get('nav') or ''
    
    return render(request, 'quotations/quotation_viewer.html', context)


@login_required
def quotation_edit(request, quotation_id):
    """Edit an existing quotation"""
    quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
    
    # Check if can be edited
    if not quotation.can_be_edited():
        messages.error(request, "This quotation has been converted and cannot be edited.")
        return redirect('quotations')
    
    user_profile = get_object_or_404(UserProfile, user=request.user)
    context = {}
    context['quotation'] = quotation
    context['quotation_id'] = quotation.id
    context['quotation_number'] = quotation.quotation_number
    context['quotation_date'] = quotation.quotation_date.strftime('%Y-%m-%d')
    context['valid_until'] = quotation.valid_until.strftime('%Y-%m-%d') if quotation.valid_until else ''
    context['quotation_data'] = json.loads(quotation.quotation_json)
    context['edit_mode'] = True
    
    if request.method == 'POST':
        quotation_data = request.POST
        
        # Validate
        validation_error = invoice_data_validator(quotation_data)
        if validation_error:
            context["error_message"] = validation_error
            return render(request, 'quotations/quotation_edit.html', context)
        
        # Process data
        quotation_data_processed = invoice_data_processor(quotation_data)
        
        # Check if modify customer details is enabled
        is_modified_customer = len(request.POST.getlist('modify-customer-details')) > 0
        
        # Get customer - Use the ORIGINAL FK customer if details were modified
        customer = None
        
        if is_modified_customer:
            # Keep the original FK customer when modifying details
            customer = quotation.quotation_customer
            messages.info(request, "Customer details modified. Using original customer mapping.")
        else:
            # Normal flow - match an existing customer by name (+ phone).
            customer = find_matching_customer(request.user, quotation_data)

            if not customer:
                messages.warning(request, "Customer not found. Please add the customer first or enable 'Modify Details'.")
                return redirect('customer_add')
        
        # Update quotation
        quotation.quotation_json = json.dumps(quotation_data_processed)
        quotation.quotation_customer = customer
        quotation.quotation_date = datetime.datetime.strptime(quotation_data['invoice-date'], '%Y-%m-%d')
        quotation.customer_details_modified = is_modified_customer
        
        valid_until = quotation_data.get('valid-until', '')
        if valid_until:
            quotation.valid_until = datetime.datetime.strptime(valid_until, '%Y-%m-%d').date()
        
        quotation.save()
        
        messages.success(request, f'Quotation #{quotation.quotation_number} updated successfully')
        return redirect('quotation_viewer', quotation_id=quotation.id)
    
    return render(request, 'quotations/quotation_edit.html', context)


@login_required
def quotation_delete(request, quotation_id):
    """Delete a quotation"""
    if request.method == 'POST':
        quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
        
        if not quotation.can_be_deleted():
            return JsonResponse({
                'success': False,
                'message': 'Cannot delete a quotation with an active invoice'
            }, status=400)
        
        quotation_num = quotation.quotation_number
        quotation.delete()
        
        messages.success(request, f'Quotation #{quotation_num} deleted successfully')
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False}, status=405)


@login_required
@transaction.atomic
def quotation_convert_to_invoice(request, quotation_id):
    """Convert quotation to invoice with inventory and books update"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    try:
        quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
        
        # Validate conversion
        if not quotation.can_be_converted():
            return JsonResponse({
                'success': False,
                'message': 'This quotation cannot be converted'
            }, status=400)
        
        # Parse quotation data
        quotation_data = json.loads(quotation.quotation_json)
        
        # Get next invoice number
        user_profile = get_object_or_404(UserProfile, user=request.user)
        
        if quotation.is_gst:
            # Get max invoice number across same GST
            max_invoice_number = []
            user_profiles = UserProfile.objects.filter(business_gst=user_profile.business_gst)
            for profile in user_profiles:
                max_num = Invoice.objects.filter(
                    user=profile.user, is_gst=True
                ).aggregate(Max('invoice_number'))['invoice_number__max']
                max_invoice_number.append(max_num)
            max_invoice_number = [num for num in max_invoice_number if num is not None]
            
            if max_invoice_number:
                next_invoice_number = max(max_invoice_number) + 1
            else:
                next_invoice_number = 1
        else:
            # Non-GST invoice
            next_invoice_number = Invoice.objects.filter(
                user=request.user, is_gst=False
            ).aggregate(Max('invoice_number'))['invoice_number__max']
            if not next_invoice_number:
                next_invoice_number = 1
            else:
                next_invoice_number += 1
        
        # Create invoice
        new_invoice = Invoice(
            user=request.user,
            invoice_number=next_invoice_number,
            invoice_date=datetime.date.today(),
            invoice_customer=quotation.quotation_customer,
            invoice_json=quotation.quotation_json,  # Reuse quotation JSON
            is_gst=quotation.is_gst,
            inventory_reflected=False,
            books_reflected=False
        )
        new_invoice.save()
        
        # Update inventory
        update_inventory(new_invoice, request)
        new_invoice.inventory_reflected = True
        
        # Update books
        auto_deduct_book_from_invoice(new_invoice)
        new_invoice.books_reflected = True
        
        new_invoice.save()
        
        # Link invoice to quotation (status remains unchanged - business owner will update through tracking)
        quotation.converted_invoice = new_invoice
        quotation.converted_at = timezone.now()
        quotation.converted_by = request.user
        quotation.save()
        
        messages.success(
            request, 
            f'Quotation #{quotation.quotation_number} converted to Invoice #{new_invoice.invoice_number}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Converted to Invoice #{new_invoice.invoice_number}',
            'invoice_id': new_invoice.id
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in quotation_convert_to_invoice: {error_details}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@transaction.atomic
def quotation_reconvert_to_invoice(request, quotation_id):
    """Reconvert a quotation to invoice (when previous invoice was deleted)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    try:
        quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
        
        # Validate reconversion - must be CONVERTED status but invoice deleted
        if quotation.status != 'CONVERTED':
            return JsonResponse({
                'success': False,
                'message': 'Only converted quotations can be reconverted'
            }, status=400)
        
        if quotation.converted_invoice is not None:
            return JsonResponse({
                'success': False,
                'message': 'Invoice still exists. Cannot reconvert.'
            }, status=400)
        
        # Parse quotation data
        quotation_data = json.loads(quotation.quotation_json)
        
        # Get next invoice number
        user_profile = get_object_or_404(UserProfile, user=request.user)
        
        if quotation.is_gst:
            # Get max invoice number across same GST
            max_invoice_number = []
            user_profiles = UserProfile.objects.filter(business_gst=user_profile.business_gst)
            for profile in user_profiles:
                max_num = Invoice.objects.filter(
                    user=profile.user, is_gst=True
                ).aggregate(Max('invoice_number'))['invoice_number__max']
                max_invoice_number.append(max_num)
            max_invoice_number = [num for num in max_invoice_number if num is not None]
            
            if max_invoice_number:
                next_invoice_number = max(max_invoice_number) + 1
            else:
                next_invoice_number = 1
        else:
            # Non-GST invoice
            next_invoice_number = Invoice.objects.filter(
                user=request.user, is_gst=False
            ).aggregate(Max('invoice_number'))['invoice_number__max']
            if not next_invoice_number:
                next_invoice_number = 1
            else:
                next_invoice_number += 1
        
        # Create invoice
        new_invoice = Invoice(
            user=request.user,
            invoice_number=next_invoice_number,
            invoice_date=datetime.date.today(),
            invoice_customer=quotation.quotation_customer,
            invoice_json=quotation.quotation_json,  # Reuse quotation JSON
            is_gst=quotation.is_gst,
            inventory_reflected=False,
            books_reflected=False
        )
        new_invoice.save()
        
        # Update inventory
        update_inventory(new_invoice, request)
        new_invoice.inventory_reflected = True
        
        # Update books
        auto_deduct_book_from_invoice(new_invoice)
        new_invoice.books_reflected = True
        
        new_invoice.save()
        
        # Update quotation with new invoice
        quotation.converted_invoice = new_invoice
        quotation.converted_at = timezone.now()
        quotation.converted_by = request.user
        quotation.save()
        
        messages.success(
            request, 
            f'Quotation #{quotation.quotation_number} reconverted to Invoice #{new_invoice.invoice_number}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Reconverted to Invoice #{new_invoice.invoice_number}',
            'invoice_id': new_invoice.id
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in quotation_reconvert_to_invoice: {error_details}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
def quotation_approve(request, quotation_id):
    """Approve a quotation (change status to APPROVED)"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        }, status=405)
    
    quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
    
    if quotation.status != 'DRAFT':
        return JsonResponse({
            'success': False,
            'message': 'Only draft quotations can be approved'
        }, status=400)
    
    quotation.status = 'APPROVED'
    quotation.save()
    
    messages.success(request, f'Quotation #{quotation.quotation_number} approved')
    return JsonResponse({
        'success': True,
        'message': f'Quotation #{quotation.quotation_number} approved successfully'
    })


def quotation_cart(request):
    """
    Quotation Cart, reachable three ways — see resolve_cart_context():
      staff     /quotation/cart                     (logged in)
      customer  /quotation/cart?cid=GS1C22          (no login)
      employee  /quotation/cart?u=emp&users_filter=1 (no login)
    """
    try:
        ctx = resolve_cart_context(request)
    except CartAccessError as err:
        return render(request, 'quotations/quotation_cart_denied.html',
                      {'message': str(err)}, status=403)

    # Employee handed several businesses: pick one before any catalog is loaded,
    # since a quotation belongs to exactly one business. Only employees on mobile ever
    # see this, so it wears the mobile shell.
    if ctx.needs_business_choice:
        return render(request, 'quotations/quotation_cart_pick_business.html', {
            'base_template': 'mobile_v1/base.html',
            'businesses': ctx.businesses,
            'users_filter': request.GET.get('users_filter', ''),
            'admin': request.GET.get('admin', ''),
        })

    business_profile = UserProfile.objects.filter(user=ctx.business_user).first()

    categories = list(
        ProductCategory.objects.filter(user=ctx.business_user)
        .values('id', 'category_name', 'parent_category_id')
    )

    # Customers are only sent when the actor may choose one. A customer-mode visitor is
    # locked to themselves, so the business's customer list never reaches their browser.
    customers = []
    if ctx.can_choose_customer:
        customers = list(
            Customer.objects.filter(user=ctx.business_user)
            .order_by('customer_name')
            .values('id', 'customer_name', 'customer_phone', 'customer_gst')
        )

    # Free-text tag fields: offer a filter only when this business actually uses one.
    def _cart_distinct(field):
        return list(
            Product.objects.filter(user=ctx.business_user)
            .exclude(**{field + '__isnull': True})
            .exclude(**{field: ''})
            .values_list(field, flat=True)
            .distinct().order_by(field)
        )

    divisions = _cart_distinct('product_division_category')
    model_categories = _cart_distinct('product_model_category')
    colours = _cart_distinct('product_colour')

    # Default the grouping to whichever dimension this business actually populates:
    # a shop that files products by division and never sets a category would otherwise
    # open on a single "Uncategorized" heap.
    has_categorised_products = Product.objects.filter(
        user=ctx.business_user, product_category__isnull=False
    ).exists()
    default_group_by = 'category' if has_categorised_products else ('division' if divisions else 'category')

    fixed = ctx.fixed_customer

    # Public actors arrive from the mobile app, so wear its shell and its bottom nav —
    # the desktop base would strand them on a page with no way back, and its links
    # would drop the cid / users_filter params that identify them.
    if ctx.actor == 'customer':
        base_template, navbar_template = 'mobile_v1/base.html', 'mobile_v1/navbarC.html'
    elif ctx.actor == 'employee':
        base_template, navbar_template = 'mobile_v1/base.html', 'mobile_v1/navbarE.html'
    else:
        base_template, navbar_template = 'base.html', None

    return render(request, 'quotations/quotation_cart.html', {
        'base_template': base_template,
        'navbar_template': navbar_template,
        'divisions': divisions,
        'model_categories': model_categories,
        'colours': colours,
        'has_categories': has_categorised_products,
        'default_group_by': default_group_by,
        'actor': ctx.actor,
        'is_public': ctx.actor != 'staff',
        'can_choose_customer': ctx.can_choose_customer,
        'fixed_customer': fixed,
        'business_profile': business_profile,

        # Rendered into the page rather than fetched by the browser: the querysets are
        # scoped and field-whitelisted here, on the server, so nothing the client can
        # call will hand out another business's data or the product cost price.
        'products_json': json.dumps(cart_product_payload(ctx.business_user)),
        'categories_json': json.dumps(categories),
        'customers_json': json.dumps(customers),
        'fixed_customer_json': json.dumps({
            'id': fixed.id,
            'customer_name': fixed.customer_name,
            'customer_phone': fixed.customer_phone or '',
            'customer_gst': (fixed.customer_gst or '').strip(),
        } if fixed else None),

        # Echoed onto the checkout POST so the mode survives the round-trip.
        'cart_query': request.GET.urlencode(),
    })


def quotation_cart_checkout(request):
    """
    Turn a Quotation Cart into a DRAFT Quotation.

    The client sends only product ids, quantities and per-line discounts. Rates and
    GST% are re-read from the Product table and every amount is recomputed here —
    the totals the browser displays are a preview and are never trusted, since the
    cart lives in localStorage and this endpoint is destined to be public.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    try:
        ctx = resolve_cart_context(request)
    except CartAccessError as err:
        return JsonResponse({'success': False, 'message': str(err)}, status=403)

    if ctx.business_user is None:
        return JsonResponse({'success': False, 'message': 'Choose a business first.'}, status=400)

    business_user = ctx.business_user

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Malformed request'}, status=400)

    items = payload.get('items') or []
    if not items:
        return JsonResponse({'success': False, 'message': 'Cart is empty'}, status=400)

    customer_input = payload.get('customer') or {}
    existing_customer = None

    if ctx.fixed_customer is not None:
        # Customer mode: the buyer is whoever the cid resolved to. Anything the
        # browser sent about the customer is ignored, so a customer holding their own
        # code cannot raise a quotation billed to somebody else.
        existing_customer = ctx.fixed_customer
    elif customer_input.get('id'):
        # Picked from the dropdown: read the details straight off the saved Customer
        # rather than trusting whatever the browser echoed back.
        try:
            existing_customer = Customer.objects.get(
                id=customer_input['id'], user=business_user
            )
        except (Customer.DoesNotExist, ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Selected customer not found'}, status=400)

    if existing_customer:
        customer_name = existing_customer.customer_name
        customer_phone = existing_customer.customer_phone or ''
        customer_address = existing_customer.customer_address or ''
        customer_gst = (existing_customer.customer_gst or '').strip().upper()
    else:
        customer_name = (customer_input.get('name') or '').strip()
        if not customer_name:
            return JsonResponse({'success': False, 'message': 'Customer name is required'}, status=400)

        customer_phone = (customer_input.get('phone') or '').strip()
        customer_address = (customer_input.get('address') or '').strip()
        customer_gst = (customer_input.get('gst') or '').strip().upper()

        if customer_gst and len(customer_gst) != 15:
            return JsonResponse({'success': False, 'message': 'Customer GST must be 15 characters'}, status=400)

    # Same rule as quotation_create() and invoice_create(): GST mode defaults to GST,
    # but a GST quotation needs the customer's GSTIN, so a customer without one is
    # silently downgraded to non-GST. The quotation number is drawn from the matching
    # series below, after is_gst is settled, so the downgrade cannot mis-number it.
    is_gst = bool(payload.get('is_gst', True))

    auto_downgraded_to_non_gst = is_gst and not customer_gst
    if auto_downgraded_to_non_gst:
        is_gst = False

    quotation_data = {
        'customer_name': customer_name,
        'customer_address': customer_address,
        'customer_phone': customer_phone,
        'customer_gst': customer_gst,
        'vehicle_number': '',
        'igstcheck': False,
        'items': [],
    }

    total_gross = total_discount = 0.0
    total_without_gst = total_sgst = total_cgst = total_igst = total_with_gst = 0.0

    for line in items:
        try:
            product = Product.objects.get(id=line.get('id'), user=business_user)
        except (Product.DoesNotExist, ValueError, TypeError):
            return JsonResponse(
                {'success': False, 'message': 'A product in your cart no longer exists. Please refresh.'},
                status=400,
            )

        try:
            qty = int(float(line.get('qty', 0)))
        except (ValueError, TypeError):
            qty = 0
        if qty < 1:
            return JsonResponse(
                {'success': False, 'message': f'Invalid quantity for {product.model_no}'},
                status=400,
            )

        # Discount is a staff-only override. For customers and employees the client's
        # discount is ignored (discount=None falls back to the product's own), so a
        # forged payload cannot mark down the price — the read-only field is only the
        # visible half of this rule.
        line_discount = line.get('discount') if ctx.actor == 'staff' else None

        item_entry = build_quotation_item(
            product, qty,
            igstcheck=quotation_data['igstcheck'],
            discount=line_discount,
        )

        # Gross and discount are not stored on the quotation, but the cart shows them
        # as summary rows, so report them back for the confirmation dialog.
        gross = item_entry['invoice_rate_with_gst'] * qty
        total_gross += gross
        total_discount += gross - item_entry['invoice_amt_without_gst']

        total_without_gst += item_entry['invoice_amt_without_gst']
        total_sgst += item_entry['invoice_amt_sgst']
        total_cgst += item_entry['invoice_amt_cgst']
        total_igst += item_entry['invoice_amt_igst']
        total_with_gst += item_entry['invoice_amt_with_gst']

        quotation_data['items'].append(item_entry)

    quotation_data['invoice_total_amt_without_gst'] = round(total_without_gst, 2)
    quotation_data['invoice_total_amt_sgst'] = round(total_sgst, 2)
    quotation_data['invoice_total_amt_cgst'] = round(total_cgst, 2)
    quotation_data['invoice_total_amt_igst'] = round(total_igst, 2)
    quotation_data['invoice_total_amt_with_gst'] = round(total_with_gst, 2)

    today = datetime.date.today()

    with transaction.atomic():
        # select_for_update holds the row lock until commit so two concurrent
        # checkouts cannot read the same Max() and claim the same number.
        max_number = Quotation.objects.select_for_update().filter(
            user=business_user, is_gst=is_gst
        ).aggregate(Max('quotation_number'))['quotation_number__max']

        customer = existing_customer
        if customer is None:
            customer, _ = Customer.objects.get_or_create(
                user=business_user,
                customer_name=customer_name.upper(),
                defaults={
                    'customer_address': customer_address,
                    'customer_phone': customer_phone,
                    'customer_gst': customer_gst,
                },
            )

        new_quotation = Quotation(
            user=business_user,
            quotation_number=(max_number or 0) + 1,
            quotation_date=today,
            valid_until=today + datetime.timedelta(days=30),
            quotation_customer=customer,
            quotation_json=json.dumps(quotation_data),
            is_gst=is_gst,
            # Always DRAFT: a public checkout must not touch inventory or books until
            # a human at the business approves it.
            status='DRAFT',
            created_from_cart=True,
            created_by_customer=(ctx.actor == 'customer'),
            notes=f'Created from Quotation Cart ({ctx.actor})',
        )
        new_quotation.save()

    # A public visitor has no business viewing the internal quotation page.
    redirect_url = reverse('quotation_viewer', args=[new_quotation.id]) if ctx.actor == 'staff' else None

    business_profile = UserProfile.objects.filter(user=business_user).first()
    business_title = (business_profile.business_title if business_profile else '') or ''
    business_phone = (business_profile.business_phone if business_profile else '') or ''

    # The SMS / WhatsApp always goes to the shop, whoever built the cart: the shop is
    # the party that has to act on the quotation.
    share_phone, share_to = business_phone, business_title

    return JsonResponse({
        'success': True,
        'quotation_id': new_quotation.id,
        'quotation_number': new_quotation.quotation_number,
        'quotation_label': ('' if is_gst else 'QT-') + str(new_quotation.quotation_number),
        'is_gst': is_gst,
        'gst_downgraded': auto_downgraded_to_non_gst,
        'customer_name': customer_name,
        'customer_phone': customer_phone,
        'actor': ctx.actor,
        'share_phone': share_phone,
        'share_to': share_to,
        'quotation_date': today.strftime('%d-%m-%Y'),
        'business_title': business_title,
        'business_phone': business_phone,
        'business_brand': (business_profile.business_brand if business_profile else '') or '',
        'item_count': len(quotation_data['items']),
        # Model no + qty + line total, for the SMS / WhatsApp message.
        'items': [
            {
                'model_no': i['invoice_model_no'],
                'qty': i['invoice_qty'],
                'amount': i['invoice_amt_with_gst'],
            }
            for i in quotation_data['items']
        ],
        # The server's own figures — what the quotation was actually saved with.
        'totals': {
            'gross': round(total_gross, 2),
            'discount': round(total_discount, 2),
            'taxable': quotation_data['invoice_total_amt_without_gst'],
            'cgst': quotation_data['invoice_total_amt_cgst'],
            'sgst': quotation_data['invoice_total_amt_sgst'],
            'igst': quotation_data['invoice_total_amt_igst'],
            'grand_total': quotation_data['invoice_total_amt_with_gst'],
        },
        'redirect_url': redirect_url,
    })

@login_required
def quotation_update_customer(request, quotation_id):
    """Update customer details in quotation JSON only"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        }, status=405)
    
    quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
    
    try:
        # Parse request data
        data = json.loads(request.body)
        
        # Get current quotation JSON
        quotation_data = json.loads(quotation.quotation_json)
        
        # Update customer details in JSON
        quotation_data['customer_name'] = data.get('customer_name', '')
        quotation_data['customer_address'] = data.get('customer_address', '')
        quotation_data['customer_phone'] = data.get('customer_phone', '')
        
        if quotation.is_gst:
            quotation_data['customer_gst'] = data.get('customer_gst', '')
        
        if data.get('vehicle_number'):
            quotation_data['vehicle_number'] = data.get('vehicle_number')
        elif 'vehicle_number' in quotation_data:
            quotation_data['vehicle_number'] = data.get('vehicle_number', '')
        
        # Save updated JSON and mark as modified
        quotation.quotation_json = json.dumps(quotation_data)
        quotation.customer_details_modified = True
        quotation.save()
        
        messages.success(request, 'Customer details updated successfully in quotation')
        return JsonResponse({
            'success': True,
            'message': 'Customer details updated successfully (marked as modified)'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)


@login_required
def quotation_update_status(request, quotation_id):
    """Update quotation/order status for tracking"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)
    
    try:
        quotation = get_object_or_404(Quotation, id=quotation_id, user=request.user)
        new_status = request.POST.get('status')
        
        # Validate status
        valid_statuses = ['DRAFT', 'APPROVED', 'PROCESSING', 'PACKED', 'SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CONVERTED']
        if new_status not in valid_statuses:
            return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)
        
        # Update status
        old_status = quotation.status
        quotation.status = new_status
        quotation.save()
        
        # Get status display name
        status_names = {
            'DRAFT': 'Pending',
            'APPROVED': 'Approved',
            'PROCESSING': 'Processing',
            'PACKED': 'Packed',
            'SHIPPED': 'Shipped',
            'OUT_FOR_DELIVERY': 'Out for Delivery',
            'DELIVERED': 'Delivered',
            'CONVERTED': 'Completed'
        }
        
        return JsonResponse({
            'success': True,
            'message': f'Order status updated from {status_names.get(old_status, old_status)} to {status_names.get(new_status, new_status)}',
            'new_status': new_status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
