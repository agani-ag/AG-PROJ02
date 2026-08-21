# Django imports
from django.contrib import messages
from django.db.models import Max, Sum
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    Customer, Product, Invoice,
    UserProfile, Book, BookLog, Quotation, Employee
)

# Utility functions
from ..utils import invoice_data_validator
from ..utils import invoice_data_processor
from ..utils import apply_invoice_round_off
from ..templatetags.money import format_inr_smart
from ..utils import update_products_from_invoice
from ..utils import update_inventory
from ..utils import add_customer_book
from ..utils import auto_deduct_book_from_invoice
from ..utils import remove_inventory_entries_for_invoice
from ..utils import remove_book_entries_for_invoice
from ..utils import recompute_invoice_data
from ..utils import find_matching_customer

# Third-party libraries
import json
import datetime
import num2words
import html


# ================= Invoice, products and customers =============================
@login_required
def invoice_create(request):
    # if business info is blank redirect to update it
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if not user_profile.business_title:
        messages.warning(request, "Please update your business name before creating invoices.")
        return redirect('user_profile_edit')
    if not user_profile.business_gst:
        messages.warning(request, "Please update your business GST number before creating invoices.")
        return redirect('user_profile_edit')

    context = {}
    context['non_gst_invoice_number'] = Invoice.objects.filter(user=request.user, is_gst=False).aggregate(Max('invoice_number'))['invoice_number__max']
    if not context['non_gst_invoice_number']:
        context['non_gst_invoice_number'] = 1
    else:
        context['non_gst_invoice_number'] += 1

    max_invoice_number = []
    user_profiles = UserProfile.objects.filter(business_gst=user_profile.business_gst)
    for profile in user_profiles:
        max_invoice_number.append(Invoice.objects.filter(user=profile.user, is_gst=True).aggregate(Max('invoice_number'))['invoice_number__max'])
    max_invoice_number = [num for num in max_invoice_number if num is not None]

    if max_invoice_number:
        context['default_invoice_number'] = max(max_invoice_number) + 1
    else:
        context['default_invoice_number'] = 1

    context['default_invoice_date'] = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')

    if request.method == 'POST':

        invoice_data = request.POST
        non_gst_mode = 'nongstcheck' in invoice_data
        if non_gst_mode:
            is_gst = False
        else:
            is_gst = True
        
        # A GST invoice needs the customer's GSTIN. Rather than rejecting, fall back to
        # a non-GST invoice — but the number submitted with the form came from the GST
        # series, so it has to be re-drawn from the non-GST series below.
        auto_downgraded_to_non_gst = False
        if is_gst and invoice_data['customer-gst'].strip() == '':
            is_gst = False
            auto_downgraded_to_non_gst = True
            messages.info(
                request,
                "Customer has no GST Number — this was created as a NON-GST invoice."
            )

        validation_error = invoice_data_validator(invoice_data)
        if validation_error:
            context["error_message"] = validation_error
            return render(request, 'invoices/invoice_create.html', context)

        invoice_data_processed = invoice_data_processor(invoice_data)
        # Round the grand total to the nearest rupee (new invoices only). Done here, not in
        # invoice_data_processor, because that helper is shared with quotation_create.
        apply_invoice_round_off(invoice_data_processed)
        # save customer
        # Prefer the hidden customer-id (set when a customer is picked from the list);
        # otherwise fall back to a name (+ phone) match. The fallback used to require an
        # exact name+address+phone+GST match, which failed for non-GST customers whose
        # GST is stored NULL against the form's empty '' — wrongly forcing 'Add Customer'.
        customer = None
        customer_id = invoice_data.get('customer-id')
        if customer_id and customer_id.isdigit():
            customer = Customer.objects.filter(user=request.user, id=int(customer_id)).first()
        else:
            customer = find_matching_customer(request.user, invoice_data)

        if not customer:
            messages.warning(request, "Customer does not exist. Please add the customer first.")
            return redirect('customer_add')

        # save product
        # update_products_from_invoice(invoice_data_processed, request)


        # save invoice
        invoice_data_processed_json = json.dumps(invoice_data_processed)

        invoice_number = int(invoice_data['invoice-number'])
        if auto_downgraded_to_non_gst:
            # The posted number belongs to the GST series; take the next non-GST one.
            max_non_gst = Invoice.objects.filter(
                user=request.user, is_gst=False
            ).aggregate(Max('invoice_number'))['invoice_number__max']
            invoice_number = (max_non_gst or 0) + 1

        new_invoice = Invoice(user=request.user,
            invoice_number=invoice_number,
            invoice_date=datetime.datetime.strptime(invoice_data['invoice-date'], '%Y-%m-%d'),
            invoice_customer=customer, invoice_json=invoice_data_processed_json, is_gst= is_gst)
        new_invoice.save()

        update_inventory(new_invoice, request)
        auto_deduct_book_from_invoice(new_invoice)
        return redirect('invoice_viewer', invoice_id=new_invoice.id)

    return render(request, 'invoices/invoice_create.html', context)


@login_required
def invoices(request):
    context = {}
    # Get all customers for dropdown filter
    customers = Customer.objects.filter(user=request.user).order_by('customer_name')
    context['customers'] = customers
    return render(request, 'invoices/invoices.html', context)

@login_required
def invoices_ajax(request):
    """AJAX endpoint for server-side DataTables processing"""
    from datetime import timedelta
    from django.utils import timezone
    
    try:
        draw = int(request.GET.get('draw', 1))
        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 15))
        search_value = request.GET.get('search[value]', '')
        order_column_index = int(request.GET.get('order[0][column]', 0))
        order_direction = request.GET.get('order[0][dir]', 'desc')
        
        # Filter parameters
        invoice_type = request.GET.get('invoice_type', 'all')  # all, gst, non_gst, not_pushed, missing_in_books
        date_filter = request.GET.get('date_filter', 'all')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        customer_id = request.GET.get('customer_id', '')  # customer filter
        
        # Base queryset
        queryset = Invoice.objects.filter(user=request.user).select_related('invoice_customer')
        
        # Apply customer filter
        if customer_id and customer_id.isdigit():
            queryset = queryset.filter(invoice_customer__id=int(customer_id))
        
        # Apply invoice type filter
        if invoice_type == 'gst':
            queryset = queryset.filter(is_gst=True)
        elif invoice_type == 'non_gst':
            queryset = queryset.filter(is_gst=False)
        elif invoice_type == 'not_pushed':
            queryset = queryset.filter(books_reflected=False)
        elif invoice_type == 'missing_in_books':
            # Find invoices marked as reflected but with no BookLog entry
            # Only execute this expensive query when this filter is active
            existing_invoice_ids = set(BookLog.objects.filter(
                parent_book__user=request.user,
                associated_invoice__isnull=False
            ).values_list('associated_invoice_id', flat=True))
            queryset = queryset.filter(books_reflected=True).exclude(id__in=existing_invoice_ids)
        
        # Apply date filters
        if date_filter and date_filter != 'all':
            if date_filter == 'today':
                today = timezone.now().date()
                queryset = queryset.filter(invoice_date=today)
            elif date_filter == 'week':
                week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
                queryset = queryset.filter(invoice_date__gte=week_start)
            elif date_filter == 'month':
                month_start = timezone.now().date().replace(day=1)
                queryset = queryset.filter(invoice_date__gte=month_start)
            elif date_filter == 'custom' and start_date and end_date:
                try:
                    queryset = queryset.filter(invoice_date__gte=start_date, invoice_date__lte=end_date)
                except:
                    pass
        
        # Apply search filter
        if search_value:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(invoice_number__icontains=search_value) |
                Q(invoice_customer__customer_name__icontains=search_value)
            )
        
        # Total records
        total_records = Invoice.objects.filter(user=request.user).count()
        
        # Filtered records count
        filtered_records = queryset.count()
        
        # Default ordering: by invoice_date desc, then id desc
        default_ordering = ['-invoice_date', '-id']

        # Ordering
        order_columns = ['invoice_number', 'invoice_date', 'invoice_customer__customer_name']
        if 0 <= order_column_index < len(order_columns):
            order_by = order_columns[order_column_index]
            if order_direction == 'desc':
                order_by = '-' + order_by
            # Apply user-specified order first, then fallback to date & id desc
            queryset = queryset.order_by(order_by, '-invoice_date', '-id')
        else:
            # Default ordering
            queryset = queryset.order_by(*default_ordering)
        
        # Calculate total invoice amount - optimized query
        # Use values_list to only fetch invoice_json field, not all related data
        total_invoice_amount = 0.0
        invoice_jsons = queryset.values_list('invoice_json', flat=True)
        for invoice_json_str in invoice_jsons:
            try:
                invoice_json = json.loads(invoice_json_str)
                invoice_amount = float(invoice_json.get('invoice_total_amt_with_gst', 0))
                total_invoice_amount += invoice_amount
            except Exception:
                pass
        
        # Pagination - apply after total calculation
        queryset = queryset[start:start + length]
        
        # Prepare data for current page
        data = []
        for invoice in queryset:
            # Invoice number
            if invoice.is_gst:
                invoice_num = str(invoice.invoice_number)
            else:
                invoice_num = f'<span class="text-danger font-weight-bold">INV-{invoice.invoice_number}</span>'

            # Customer
            if invoice.invoice_customer:
                customer_html = f'<a href="/books/{invoice.invoice_customer.id}" style="text-decoration: none;color: black;" title="View Books">{invoice.invoice_customer.customer_name}</a>'
            else:
                customer_html = '<span class="text-danger">N/A</span>'

            # Invoice Amount (from invoice_json)
            try:
                invoice_json = json.loads(invoice.invoice_json)
                invoice_amount = float(invoice_json.get('invoice_total_amt_with_gst', 0))
            except Exception:
                invoice_amount = 0.0

            # Division Category Totals
            totals_by_category = {}
            amount_without_gst = 0.0

            for item in invoice_json.get('items', []):
                category = (
                    item.get('product_division_category')
                    or item.get('division_category')
                    or ''
                )

                if not category:
                    model = item.get('invoice_model_no')
                    if model:
                        product = Product.objects.filter(
                            user=request.user,
                            model_no=model
                        ).first()
                        if product:
                            category = product.product_division_category

                category = category.strip().upper() if category else "UNSPECIFIED"

                try:
                    amount = float(item.get("invoice_amt_without_gst") or 0)
                except:
                    qty = float(item.get("invoice_qty") or 1)
                    rate = float(item.get("invoice_rate_without_gst") or 0)
                    amount = qty * rate

                totals_by_category[category] = totals_by_category.get(category, 0) + amount
                amount_without_gst += amount

            # Actions
            actions_html = '<div class="btn-group" role="group">'
            # actions_html += f'<button type="button" onclick="popup_invoice({invoice.id})" class="btn btn-primary btn-sm btn-curve" title="Preview Invoice"><i class="fa fa-eye"></i></button>'
            # actions_html += f'<a href="/invoice/{invoice.id}" class="btn btn-warning btn-sm btn-curve" title="View Invoice"><i class="fa fa-external-link-square"></i></a>'
            actions_html += f'<a href="/invoice/{invoice.id}" class="btn btn-primary btn-sm btn-curve" title="View Invoice"><i class="fa fa-eye"></i></a>'
            if invoice.invoice_customer:
                category_json = html.escape(json.dumps(totals_by_category))
                actions_html += f'''
                        <button type="button" class="btn btn-orange btn-sm btn-curve"
                            data-category="{category_json}" data-total="{amount_without_gst}"
                            onclick="dc_invoice_map(this)" title="Division Category"><i class="fa fa-snowflake"></i></button>
                '''
            # Add push/fix button for not_pushed or missing_in_books filters
            if invoice_type in ['not_pushed', 'missing_in_books']:
                button_title = 'Push to Books' if invoice_type == 'not_pushed' else 'Fix & Push to Books'
                actions_html += f'<button type="button" onclick="pushToBooks({invoice.id})" class="btn btn-success btn-sm btn-curve" title="{button_title}"><i class="fa fa-book"></i></button>'

            customer_info = invoice.invoice_customer.customer_name if invoice.invoice_customer else "N/A"
            actions_html += f'<button type="button" class="btn btn-danger btn-sm btn-curve" data-toggle="modal" data-target="#invoiceDeleteModal" data-invoice-id="{invoice.id}" data-invoice-number="{invoice.invoice_number}, for {customer_info}" title="Delete Invoice"><i class="fa fa-trash"></i></button>'
            actions_html += '</div>'

            data.append({
                'invoice_number': invoice_num,
                'invoice_date': invoice.invoice_date.strftime('%b %d, %Y'),
                'customer': customer_html,
                'invoice_amount': f"₹ {format_inr_smart(invoice_amount)}",
                'actions': actions_html
            })

        return JsonResponse({
            'draw': draw,
            'recordsTotal': total_records,
            'recordsFiltered': filtered_records,
            'data': data,
            'total_invoice_amount': total_invoice_amount
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in invoices_ajax: {error_details}")
        return JsonResponse({
            'error': str(e),
            'details': error_details
        }, status=500)

@login_required
def invoice_viewer(request, invoice_id):
    invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)
    user_profile = get_object_or_404(UserProfile, user=request.user)

    context = {}
    context['invoice'] = invoice_obj
    context['invoice_data'] = json.loads(invoice_obj.invoice_json)
    context['currency'] = "₹"
    context['total_in_words'] = num2words.num2words(int(context['invoice_data']['invoice_total_amt_with_gst']), lang='en_IN').title()
    context['user_profile'] = user_profile
    context['nav_hide'] = request.GET.get('nav') or ''

    # Invoice → employee attribution (local Employee model). The picker only shows
    # when this business actually has active staff to credit.
    context['assigned_employee'] = invoice_obj.assigned_employee
    context['has_employees'] = Employee.objects.filter(business=request.user, is_active=True).exists()

    # Debug JSON editor: ?debug=1 / ?debug=true. Absent → normal view, no change.
    debug_mode = str(request.GET.get('debug', '')).lower() in ('1', 'true', 'yes')
    context['debug_mode'] = debug_mode
    if debug_mode:
        # Pretty-print for the editor; the backup (original) may not exist yet.
        context['invoice_json_pretty'] = json.dumps(context['invoice_data'], indent=2, ensure_ascii=False)
        context['has_backup'] = bool(invoice_obj.invoice_json_backup)

    return render(request, 'invoices/invoice_printer.html', context)


@login_required
def invoice_json_save(request, invoice_id):
    """
    Debug JSON editor save. Validates + recomputes totals from the edited items,
    keeps the ORIGINAL as a one-time backup, optionally re-reflects inventory/books
    (replacing this invoice's existing entries, never duplicating). All-or-nothing:
    any failure rolls back the JSON change too, so document / stock / books can
    never drift apart.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Malformed request'}, status=400)

    raw_json = payload.get('json')
    reflect = bool(payload.get('reflect', False))

    # 1. Parse the edited JSON.
    try:
        invoice_data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Edited content is not valid JSON.'}, status=400)

    # 2. Structural check + 3. recompute totals from items.
    try:
        invoice_data = recompute_invoice_data(invoice_data)
    except ValueError as err:
        return JsonResponse({'success': False, 'message': str(err)}, status=400)

    try:
        with transaction.atomic():
            # 4. Backup the ORIGINAL once, then never overwrite it.
            if not invoice_obj.invoice_json_backup:
                invoice_obj.invoice_json_backup = invoice_obj.invoice_json

            # 5. Save the recomputed JSON.
            invoice_obj.invoice_json = json.dumps(invoice_data)
            invoice_obj.save()

            # 6. Optionally replace this invoice's stock/ledger entries.
            if reflect:
                if invoice_obj.inventory_reflected:
                    remove_inventory_entries_for_invoice(invoice_obj, request.user)
                    update_inventory(invoice_obj, request)
                if invoice_obj.books_reflected:
                    remove_book_entries_for_invoice(invoice_obj)
                    auto_deduct_book_from_invoice(invoice_obj)
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Re-reflect failed: an edited line no longer matches a product '
                       '(model no / name / HSN / GST%). Nothing was saved.',
        }, status=400)
    except Exception as err:
        return JsonResponse({'success': False, 'message': f'Save failed: {err}. Nothing was saved.'}, status=400)

    totals = {
        'taxable': invoice_data['invoice_total_amt_without_gst'],
        'sgst': invoice_data['invoice_total_amt_sgst'],
        'cgst': invoice_data['invoice_total_amt_cgst'],
        'igst': invoice_data['invoice_total_amt_igst'],
        'grand_total': invoice_data['invoice_total_amt_with_gst'],
    }
    return JsonResponse({
        'success': True,
        'message': 'Saved.' + (' Inventory & books re-reflected.' if reflect else ''),
        'reflected': reflect,
        'totals': totals,
    })


@login_required
def invoice_json_restore(request, invoice_id):
    """Restore the ORIGINAL invoice_json from the backup. Optionally re-reflect so
    stock/ledger resync to the original after edited values were reflected."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)

    if not invoice_obj.invoice_json_backup:
        return JsonResponse({'success': False, 'message': 'No original backup to restore.'}, status=400)

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        payload = {}
    reflect = bool(payload.get('reflect', False))

    try:
        with transaction.atomic():
            invoice_obj.invoice_json = invoice_obj.invoice_json_backup
            invoice_obj.save()
            if reflect:
                if invoice_obj.inventory_reflected:
                    remove_inventory_entries_for_invoice(invoice_obj, request.user)
                    update_inventory(invoice_obj, request)
                if invoice_obj.books_reflected:
                    remove_book_entries_for_invoice(invoice_obj)
                    auto_deduct_book_from_invoice(invoice_obj)
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Restore re-reflect failed: original line no longer matches a product. Nothing was changed.',
        }, status=400)
    except Exception as err:
        return JsonResponse({'success': False, 'message': f'Restore failed: {err}. Nothing was changed.'}, status=400)

    return JsonResponse({'success': True, 'message': 'Original restored.' + (' Re-reflected.' if reflect else '')})


@login_required
def invoice_delete(request):
    if request.method == "POST":
        invoice_id = request.POST["invoice_id"]
        invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        
        # Check if this invoice was converted from a quotation
        source_quotation = None
        try:
            source_quotation = Quotation.objects.filter(converted_invoice=invoice_obj).first()
        except:
            pass
        
        # Check if user wants to move invoice to quotation before deleting
        if len(request.POST.getlist('move-to-quotation')):
            if source_quotation:
                # Invoice came from a quotation - just reset the original quotation instead of creating duplicate
                source_quotation.converted_invoice = None
                source_quotation.converted_at = None
                source_quotation.converted_by = None
                source_quotation.status = 'DRAFT'  # Reset to DRAFT so it can be edited/reconverted
                source_quotation.notes = (source_quotation.notes or '') + f'\nInvoice #{invoice_obj.invoice_number} was deleted and quotation restored.'
                source_quotation.save()
                messages.success(request, f'Invoice #{invoice_obj.invoice_number} deleted. Original Quotation #{source_quotation.quotation_number} has been restored as DRAFT.')
            else:
                # Invoice was not from a quotation - create new quotation
                try:
                    # Get next quotation number
                    user_profile = get_object_or_404(UserProfile, user=request.user)
                    
                    if invoice_obj.is_gst:
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
                            next_quotation_number = max(max_quotation_number) + 1
                        else:
                            next_quotation_number = 1
                    else:
                        # Non-GST quotation
                        next_quotation_number = Quotation.objects.filter(
                            user=request.user, is_gst=False
                        ).aggregate(Max('quotation_number'))['quotation_number__max']
                        if not next_quotation_number:
                            next_quotation_number = 1
                        else:
                            next_quotation_number += 1
                    
                    # Create quotation with invoice data
                    new_quotation = Quotation(
                        user=request.user,
                        quotation_number=next_quotation_number,
                        quotation_date=invoice_obj.invoice_date,
                        valid_until=(invoice_obj.invoice_date + datetime.timedelta(days=30)),
                        quotation_customer=invoice_obj.invoice_customer,
                        quotation_json=invoice_obj.invoice_json,  # Copy invoice JSON
                        is_gst=invoice_obj.is_gst,
                        status='DRAFT',
                        notes=f'Created from deleted Invoice #{invoice_obj.invoice_number}'
                    )
                    new_quotation.save()
                    
                    messages.success(request, f'Invoice #{invoice_obj.invoice_number} moved to Quotation #{new_quotation.quotation_number}')
                except Exception as e:
                    messages.error(request, f'Error moving to quotation: {str(e)}')
        elif source_quotation:
            # User didn't check "Move to Quotation" but invoice came from quotation
            # Just reset the source quotation without moving
            source_quotation.converted_invoice = None
            source_quotation.converted_at = None
            source_quotation.converted_by = None
            source_quotation.save()
            messages.info(request, f'Invoice deleted. Source Quotation #{source_quotation.quotation_number} has been reset.')
        
        # Proceed with normal deletion process
        if len(request.POST.getlist('inventory-del')):
            remove_inventory_entries_for_invoice(invoice_obj, request.user)
        if len(request.POST.getlist('book-del')):
            try:
                booklog_obj = get_object_or_404(BookLog,associated_invoice=invoice_obj)
                book = get_object_or_404(Book,user=request.user,id=booklog_obj.parent_book.id)
            except:
                messages.warning(request, f'Missing Invoice #{invoice_obj.invoice_number} on books, safely removed invoice.')
                invoice_obj.delete()
                return redirect('invoices')
            booklog_obj.delete()
            new_total = BookLog.objects.filter(parent_book=book).aggregate(Sum('change'))['change__sum']
            new_last_log = BookLog.objects.filter(parent_book=book).last()
            if not new_total:
                new_total = 0
            book.current_balance = new_total
            book.last_log = new_last_log
            book.save()
        invoice_obj.delete()
        
        if not len(request.POST.getlist('move-to-quotation')):
            messages.success(request, f'Invoice #{invoice_obj.invoice_number} deleted successfully')
    return redirect('invoices')


@login_required
def invoice_push_to_books(request, invoice_id):
    """Manually push an invoice to books if it wasn't reflected"""
    if request.method == 'POST':
        try:
            invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)
            
            # Check if there's already a BookLog entry for this invoice
            existing_booklog = BookLog.objects.filter(associated_invoice=invoice).first()
            
            if existing_booklog:
                return JsonResponse({
                    'success': False,
                    'message': 'Invoice already has a book entry'
                }, status=400)
            
            # If books_reflected is True but no BookLog exists, this is a data inconsistency
            # Reset the flag to allow proper pushing
            if invoice.books_reflected:
                invoice.books_reflected = False
                invoice.save()
            
            # Push to books
            auto_deduct_book_from_invoice(invoice)

            # Update the flag
            invoice.books_reflected = True
            invoice.save()
            
            messages.success(request, f'Invoice #{invoice.invoice_number} successfully pushed to books')
            return JsonResponse({
                'success': True,
                'message': f'Invoice #{invoice.invoice_number} pushed to books successfully'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=405)

# ================= Invoice API Views ===========================
@login_required
def customerInvoiceFilter(request):
    customer_id = request.GET.get('customer')

    invoices = Invoice.objects.filter(
        user=request.user,
        invoice_customer_id=customer_id
    ).order_by('-id')

    data = []
    for inv in invoices:
        data.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date.strftime("%Y-%m-%d"),
            "non_gst": inv.is_gst == False,
        })

    return JsonResponse(data, safe=False)


@login_required
def invoice_assign_employee(request, invoice_id):
    """
    Credit an invoice to one of this business's own staff (local Employee model).

    GET  → the active employees to choose from + who (if anyone) is already assigned.
    POST → {employee_id} assigns; a blank employee_id clears the assignment.

    Replaces the old external-project proxy: attribution now lives in this database.
    """
    from django.utils import timezone

    invoice = get_object_or_404(Invoice, user=request.user, id=invoice_id)

    if request.method == 'GET':
        employees = list(
            Employee.objects.filter(business=request.user, is_active=True)
            .order_by('name').values('id', 'name')
        )
        current = None
        if invoice.assigned_employee_id:
            current = {'id': invoice.assigned_employee_id, 'name': invoice.assigned_employee.name}
        return JsonResponse({'employees': employees, 'current': current})

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    try:
        emp_id = (json.loads(request.body) or {}).get('employee_id')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Malformed request.'}, status=400)

    # Blank clears the assignment.
    if not emp_id:
        invoice.assigned_employee = None
        invoice.assigned_employee_at = None
        invoice.save(update_fields=['assigned_employee', 'assigned_employee_at'])
        return JsonResponse({'ok': True, 'cleared': True})

    try:
        employee = Employee.objects.get(id=emp_id, business=request.user, is_active=True)
    except (Employee.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Employee not found.'}, status=400)

    was_assigned = invoice.assigned_employee_id is not None
    invoice.assigned_employee = employee
    invoice.assigned_employee_at = timezone.now()
    invoice.save(update_fields=['assigned_employee', 'assigned_employee_at'])
    return JsonResponse({
        'ok': True,
        'reassigned': was_assigned,
        'employee': {'id': employee.id, 'name': employee.name},
    })
