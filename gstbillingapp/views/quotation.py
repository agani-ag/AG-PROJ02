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
    find_matching_customer,
    apply_invoice_round_off,
    remove_inventory_entries_for_invoice,
    remove_book_entries_for_invoice,
    resync_quotation_prices,
    json_compact,
    CartError,
)
from ..templatetags.money import format_inr_smart

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
        quotation_data_processed_json = json_compact(quotation_data_processed)
        
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
        
        # Base queryset. An unconfirmed mobile order (a cart the buyer is still building)
        # is private to the mobile user until they confirm it — it only surfaces here once
        # it becomes PENDING, so the shop never approves a half-finished order.
        queryset = (Quotation.objects.filter(user=request.user)
                    .exclude(created_from_cart=True, status='DRAFT')
                    .select_related('quotation_customer'))

        # Apply customer filter
        if customer_id and customer_id.isdigit():
            queryset = queryset.filter(quotation_customer__id=int(customer_id))
        
        # Apply type filter
        if quotation_type == 'gst':
            queryset = queryset.filter(is_gst=True)
        elif quotation_type == 'non_gst':
            queryset = queryset.filter(is_gst=False)
        
        # Apply status filter
        if status_filter == 'pending':
            queryset = queryset.filter(status='PENDING')
        elif status_filter == 'draft':
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

        # Keep mobile-placed orders priced at today's catalog, so the Amount column and the
        # Total card below are live — the same auto-sync the quotation viewer does on open.
        # (Only PENDING/APPROVED cart orders reach this list; drafts are hidden and invoiced
        # ones are skipped inside resync.)
        for q in queryset.filter(created_from_cart=True):
            resync_quotation_prices(q)

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

            # Where the order came from, so staff can spot a mobile order that needs
            # verifying vs one they raised on the desktop themselves.
            src = quotation.order_source
            if src == 'customer':
                quotation_num += ' <span class="badge badge-info" title="Placed by the customer in the app"><i class="fas fa-mobile-alt"></i> Customer app</span>'
            elif src == 'employee':
                emp_name = quotation.order_employee.name if quotation.order_employee else ''
                suffix = f' · {emp_name}' if emp_name else ''
                quotation_num += f' <span class="badge badge-primary" title="Placed by field-staff in the app"><i class="fas fa-mobile-alt"></i> Employee app{suffix}</span>'
            elif src == 'app':
                quotation_num += ' <span class="badge badge-info" title="From the mobile app"><i class="fas fa-mobile-alt"></i> Mobile app</span>'
            else:
                quotation_num += ' <span class="badge badge-light border" title="Created on the desktop"><i class="fas fa-desktop"></i> Desktop</span>'

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
                'PENDING': '<span class="badge badge-warning"><i class="fas fa-hourglass-half"></i> Pending Approval</span>',
                'DRAFT': '<span class="badge badge-secondary">Draft</span>',
                'APPROVED': '<span class="badge badge-success">Approved</span>',
                'CONVERTED': '<span class="badge badge-dark"><i class="fas fa-check-double"></i> Invoiced</span>'
            }
            status_html = status_badges.get(quotation.status, quotation.status)

            # Actions — the list is for triage: view, edit, and (for a pending mobile
            # order) approve / reject. Converting to an invoice is done inside the viewer.
            actions_html = '<div class="btn-group" role="group">'
            actions_html += f'<a href="/quotation/{quotation.id}" class="btn btn-primary btn-sm btn-curve" title="View"><i class="fa fa-eye"></i></a>'

            if quotation.can_be_edited():
                actions_html += f'<a href="/quotation/edit/{quotation.id}" class="btn btn-warning btn-sm btn-curve" title="Edit"><i class="fa fa-edit"></i></a>'

            if quotation.needs_approval:
                actions_html += f'<button type="button" onclick="approveQuotation({quotation.id})" class="btn btn-success btn-sm btn-curve" title="Approve order"><i class="fa fa-check"></i></button>'

            if quotation.converted_invoice:
                actions_html += f'<a href="/invoice/{quotation.converted_invoice.id}" class="btn btn-info btn-sm btn-curve" title="View Invoice"><i class="fa fa-file-invoice"></i></a>'

            if quotation.can_be_deleted():
                actions_html += f'<button type="button" class="btn btn-danger btn-sm btn-curve" onclick="deleteQuotation({quotation.id})" title="Delete"><i class="fa fa-trash"></i></button>'

            actions_html += '</div>'

            data.append({
                'quotation_number': quotation_num,
                'quotation_date': quotation.quotation_date.strftime('%b %d, %Y'),
                'customer': customer_html,
                'quotation_amount': f"₹ {format_inr_smart(quotation_amount)}",
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

    # A mobile-placed order stays priced at today's catalog: re-sync it whenever the admin
    # opens it, exactly as the mobile order page does for the buyer. (Desktop-created
    # quotations are left to the manual "Sync Prices" button.) Best-effort — an already-
    # invoiced or unmappable quotation is left untouched.
    if quotation_obj.created_from_cart:
        resync_quotation_prices(quotation_obj)

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
        quotation.quotation_json = json_compact(quotation_data_processed)
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

        # Bring the quotation up to the current catalog first, so the invoice freezes in
        # today's prices (a quotation is live; an invoice is fixed). Best-effort — a line
        # with no resolvable product just keeps its saved price.
        resync_quotation_prices(quotation)
        quotation.refresh_from_db()

        # Parse quotation data, then round the grand total to the nearest rupee for the
        # INVOICE (the quotation keeps its exact figure).
        quotation_data = json.loads(quotation.quotation_json)
        apply_invoice_round_off(quotation_data)

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
            invoice_json=json_compact(quotation_data),  # rounded grand total for the invoice
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
        
        # A DESKTOP quotation is a pure duplicate of the invoice once converted, so it is
        # DELETED — the invoice becomes the single source of truth, and nothing lingers on
        # the quotation list. Re-making one is the invoice viewer's "convert to quotation".
        #
        # A MOBILE order (created_from_cart) is NOT deleted. It is the customer's own record
        # of what they ordered and /m/c/orders lists exactly these rows, so deleting it would
        # empty their order history the moment the order was billed. It is marked CONVERTED
        # and linked instead — which the orders screen already renders as an "Invoiced" badge,
        # and which keeps the reconvert / invoice-delete-restore paths working for orders.
        q_number = quotation.quotation_number
        if quotation.created_from_cart:
            quotation.status = 'CONVERTED'
            quotation.converted_invoice = new_invoice
            quotation.converted_at = timezone.now()
            quotation.converted_by = request.user
            quotation.save()
        else:
            quotation.delete()

        messages.success(
            request,
            f'Quotation #{q_number} converted to Invoice #{new_invoice.invoice_number}'
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
        
        # Parse quotation data, then round the grand total to the nearest rupee for the
        # INVOICE (the quotation keeps its exact figure).
        quotation_data = json.loads(quotation.quotation_json)
        apply_invoice_round_off(quotation_data)

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
            invoice_json=json_compact(quotation_data),  # rounded grand total for the invoice
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


def _next_quotation_number(user, is_gst):
    """Next quotation number — GST series is shared across the same business GST,
    non-GST is per user (mirrors quotation_create / invoice_delete's move flow)."""
    if is_gst:
        user_profile = get_object_or_404(UserProfile, user=user)
        maxes = []
        for profile in UserProfile.objects.filter(business_gst=user_profile.business_gst):
            m = Quotation.objects.filter(user=profile.user, is_gst=True).aggregate(
                Max('quotation_number'))['quotation_number__max']
            if m is not None:
                maxes.append(m)
        return (max(maxes) + 1) if maxes else 1
    m = Quotation.objects.filter(user=user, is_gst=False).aggregate(
        Max('quotation_number'))['quotation_number__max']
    return (m + 1) if m else 1


def _quotation_from_invoice(invoice, note):
    """Build (unsaved) a DRAFT quotation carrying this invoice's customer + items."""
    return Quotation(
        user=invoice.user,
        quotation_number=_next_quotation_number(invoice.user, invoice.is_gst),
        quotation_date=datetime.date.today(),
        valid_until=(datetime.date.today() + datetime.timedelta(days=30)),
        quotation_customer=invoice.invoice_customer,
        quotation_json=invoice.invoice_json,   # same shape as quotation_json
        is_gst=invoice.is_gst,
        status='DRAFT',
        notes=note,
    )


@login_required
@transaction.atomic
def invoice_to_quotation(request, invoice_id):
    """Turn an invoice back into a quotation. Two modes chosen from the viewer:

      mode='move' — delete this invoice (reversing its inventory + books) and
                    convert it into a fresh DRAFT quotation. If the invoice itself
                    came from a quotation, that original quotation is restored to
                    DRAFT instead of creating a duplicate.
      mode='copy' — keep the invoice untouched and ALSO create a DRAFT quotation
                    copy of it.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

    mode = request.POST.get('mode', 'copy')
    try:
        invoice = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        inv_no = invoice.invoice_number

        if mode == 'move':
            # If this invoice was produced by converting a quotation, restore THAT
            # quotation rather than spawning a second one.
            source_q = Quotation.objects.filter(user=request.user, converted_invoice=invoice).first()

            remove_inventory_entries_for_invoice(invoice, request.user)
            remove_book_entries_for_invoice(invoice)

            if source_q:
                source_q.converted_invoice = None
                source_q.converted_at = None
                source_q.converted_by = None
                source_q.status = 'DRAFT'
                source_q.quotation_json = invoice.invoice_json  # keep any invoice-side edits
                source_q.notes = (source_q.notes or '') + \
                    f'\nInvoice #{inv_no} deleted; quotation restored.'
                source_q.save()
                quotation = source_q
            else:
                quotation = _quotation_from_invoice(invoice, f'Converted from deleted Invoice #{inv_no}')
                quotation.save()

            invoice.delete()
            messages.success(
                request,
                f'Invoice #{inv_no} converted back to Quotation #{quotation.quotation_number}.')
            return JsonResponse({
                'success': True,
                'mode': 'move',
                'message': f'Invoice deleted · now Quotation #{quotation.quotation_number}',
                'quotation_id': quotation.id,
            })

        # mode == 'copy' — invoice stays, add a quotation copy.
        quotation = _quotation_from_invoice(invoice, f'Duplicated from Invoice #{inv_no}')
        quotation.save()
        messages.success(
            request,
            f'Quotation #{quotation.quotation_number} created from Invoice #{inv_no} '
            f'(invoice kept).')
        return JsonResponse({
            'success': True,
            'mode': 'copy',
            'message': f'Duplicated as Quotation #{quotation.quotation_number}',
            'quotation_id': quotation.id,
        })

    except Exception as e:
        import traceback
        print(f"Error in invoice_to_quotation: {traceback.format_exc()}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def quotation_approve(request, quotation_id):
    """Approve a mobile order — moves it out of Pending into the fulfilment pipeline."""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        }, status=405)

    quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)

    # Only a pending mobile order needs approval. Desktop drafts don't.
    if quotation.status != 'PENDING':
        return JsonResponse({
            'success': False,
            'message': 'Only pending orders can be approved'
        }, status=400)

    quotation.status = 'APPROVED'
    quotation.save()

    messages.success(request, f'Order #{quotation.quotation_number} approved')
    return JsonResponse({
        'success': True,
        'message': f'Order #{quotation.quotation_number} approved successfully'
    })


@login_required
def quotation_resync_prices(request, quotation_id):
    """Re-price a quotation to the current product rates, GST% and discounts. A quotation
    stays live until it's billed, so this is the manual 'catch up to today's prices' action
    (mobile does it automatically when the buyer opens the order)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

    quotation = get_object_or_404(Quotation, user=request.user, id=quotation_id)
    r = resync_quotation_prices(quotation)

    if r['reason'] == 'invoiced':
        return JsonResponse({'success': False, 'message': 'This quotation is already an invoice — its prices are frozen.'}, status=400)
    if r['reason'] in ('unmapped', 'product_missing'):
        return JsonResponse({'success': False, 'message': "Some lines aren't linked to a current product, so prices can't be synced automatically. Edit the quotation to update them."}, status=400)
    if r['reason'] == 'igst':
        return JsonResponse({'success': False, 'message': "Inter-state (IGST) quotations can't be auto-synced. Edit the quotation to update prices."}, status=400)

    if r['changed']:
        msg = f"Prices updated to today's rates — new total ₹ {format_inr_smart(r['new_total'])}."
    else:
        msg = 'Already up to date — prices match the current catalog.'
    return JsonResponse({'success': True, 'changed': r['changed'], 'message': msg})


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
        quotation.quotation_json = json_compact(quotation_data)
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


