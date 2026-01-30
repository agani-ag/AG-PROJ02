# Django imports
from django.contrib import messages
from django.db.models import Max
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.utils import timezone

# Models
from ..models import Customer, Quotation, Invoice, UserProfile

# Utility functions
from ..utils import (
    invoice_data_validator,
    invoice_data_processor,
    update_products_from_invoice,
    update_inventory,
    auto_deduct_book_from_invoice
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
        
        if is_gst and quotation_data['customer-gst'].strip() == '':
            messages.warning(request, "GST Quotation requires Customer GST Number.")
            return render(request, 'quotations/quotation_create.html', context)
        
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
            # When modifying details, still need to find/create a base customer
            # Try to find existing customer by name only
            try:
                customer = Customer.objects.filter(
                    user=request.user,
                    customer_name=quotation_data['customer-name']
                ).first()
            except:
                pass
            
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
            # Normal flow - exact match required
            try:
                customer = Customer.objects.get(
                    user=request.user,
                    customer_name=quotation_data['customer-name'],
                    customer_address=quotation_data['customer-address'],
                    customer_phone=quotation_data['customer-phone'],
                    customer_gst=quotation_data['customer-gst']
                )
            except Customer.DoesNotExist:
                pass

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
        
        new_quotation = Quotation(
            user=request.user,
            quotation_number=int(quotation_data['invoice-number']),  # Reusing form field name
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
                'CONVERTED': '<span class="badge badge-info">Converted</span>'
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
            # Normal flow - validate customer from form (must match existing)
            try:
                customer = Customer.objects.get(
                    user=request.user,
                    customer_name=quotation_data['customer-name'],
                    customer_address=quotation_data['customer-address'],
                    customer_phone=quotation_data['customer-phone'],
                    customer_gst=quotation_data['customer-gst']
                )
            except Customer.DoesNotExist:
                pass

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
        
        # Mark quotation as delivered (will be marked as CONVERTED when customer confirms receipt)
        quotation.status = 'DELIVERED'
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
