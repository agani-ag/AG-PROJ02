# Django imports
from django.contrib import messages
from django.db.models import Max, Sum
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import Customer
from ..models import Invoice
from ..models import UserProfile
from ..models import Book
from ..models import BookLog

# Utility functions
from ..utils import invoice_data_validator
from ..utils import invoice_data_processor
from ..utils import update_products_from_invoice
from ..utils import update_inventory
from ..utils import add_customer_book
from ..utils import auto_deduct_book_from_invoice
from ..utils import remove_inventory_entries_for_invoice

# Third-party libraries
import json
import datetime
import num2words


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
        
        if is_gst and invoice_data['customer-gst'].strip() == '':
            messages.warning(request, "GST Invoice requires Customer GST Number.")
            return render(request, 'invoices/invoice_create.html', context)

        validation_error = invoice_data_validator(invoice_data)
        if validation_error:
            context["error_message"] = validation_error
            return render(request, 'invoices/invoice_create.html', context)

        invoice_data_processed = invoice_data_processor(invoice_data)
        # save customer
        customer = None

        try:
            customer = Customer.objects.get(user=request.user,
                        customer_name=invoice_data['customer-name'],
                        customer_address=invoice_data['customer-address'],
                        customer_phone=invoice_data['customer-phone'],
                        customer_gst=invoice_data['customer-gst'])
        except:
            pass
        
        if not customer:
            # customer = Customer(user=request.user,
            #     customer_name=invoice_data['customer-name'],
            #     customer_address=invoice_data['customer-address'],
            #     customer_phone=invoice_data['customer-phone'],
            #     customer_gst=invoice_data['customer-gst'])
            # # create customer book
            # customer.save()
            # add_customer_book(customer)
            messages.warning(request, "Customer does not exist. Please add the customer first.")
            return redirect('customer_add')

        # save product
        update_products_from_invoice(invoice_data_processed, request)


        # save invoice
        invoice_data_processed_json = json.dumps(invoice_data_processed)
        new_invoice = Invoice(user=request.user,
            invoice_number=int(invoice_data['invoice-number']),
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

            # Actions
            actions_html = '<div class="btn-group" role="group">'
            actions_html += f'<button type="button" onclick="popup_invoice({invoice.id})" class="btn btn-primary btn-sm btn-curve" title="Preview Invoice"><i class="fa fa-eye"></i></button>'
            actions_html += f'<a href="/invoice/{invoice.id}" class="btn btn-warning btn-sm btn-curve" title="View Invoice"><i class="fa fa-external-link-square"></i></a>'
            if invoice.invoice_customer:
                actions_html += f'<a href="/customer/edit/{invoice.invoice_customer.id}" class="btn btn-orange btn-sm btn-curve" title="Edit Customer"><i class="fa fa-user"></i></a>'
            
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
                'invoice_amount': f"₹ {invoice_amount:,.2f}",
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
    return render(request, 'invoices/invoice_printer.html', context)


@login_required
def invoice_delete(request):
    if request.method == "POST":
        invoice_id = request.POST["invoice_id"]
        invoice_obj = get_object_or_404(Invoice, user=request.user, id=invoice_id)
        if len(request.POST.getlist('inventory-del')):
            remove_inventory_entries_for_invoice(invoice_obj, request.user)
        if len(request.POST.getlist('book-del')):
            try:
                booklog_obj = get_object_or_404(BookLog,associated_invoice=invoice_obj)
                book = get_object_or_404(Book,user=request.user,id=booklog_obj.parent_book.id)
            except:
                messages.warning(request, f'Error Invoice #{invoice_obj.invoice_number} deletion from books')
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
