# Django imports
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Case, When, FloatField, F, Q

# Models
from ..models import (
    Invoice, Book, BookLog,
    UserProfile, Customer
)

# Forms
from ..forms import BookLogForm, BookLogFullForm

# Utility functions
from ..utils import (
    recalculate_book_current_balance
)

# Python imports
import json
import datetime
import num2words

# ===================== Book views =============================
@login_required
def books(request):
    context = {}
    context['book_list'] = Book.objects.filter(user=request.user).exclude(customer_id__isnull=True).order_by('customer__customer_name')
    return render(request, 'books/books.html', context)

@login_required
def book_logs(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book).order_by('-date')
    context['book'] = book
    context['book_logs'] = book_logs
    context['nav_hide'] = request.GET.get('nav') or ''

    totals = book_logs.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )
    # Fill in context with totals, using 0 if None
    total_purchased = totals['total_purchased'] or 0
    total_paid = totals['total_paid'] or 0
    total_returned = totals['total_returned'] or 0
    total_others = totals['total_others'] or 0
    total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
    # Calculate balance (absolute value if you want it always positive)
    context['total_balance'] = total_balance
    context['total_balance_word'] = num2words.num2words(abs(int(context['total_balance'])), lang='en_IN').title()
    context['total_purchased'] = abs(total_purchased)
    context['total_paid'] = abs(total_paid)
    context['total_returned'] = abs(total_returned)
    context['total_others'] = abs(total_others)

    return render(request, 'books/book_logs.html', context)


@login_required
def book_logs_add(request, book_id):
    context = {}
    book = get_object_or_404(Book, id=book_id, user=request.user)
    book_logs = BookLog.objects.filter(parent_book=book)
    context['book'] = book
    context['book_logs'] = book_logs
    context['form'] = BookLogForm()

    if request.method == "POST":
        book_log_form = BookLogForm(request.POST)
        invoice_no = request.POST["invoice_no"]
        invoice = None
        if invoice_no:
            try:
                invoice_no = int(invoice_no)
                invoice = Invoice.objects.get(user=request.user, invoice_number=invoice_no)
            except:
                context['error_message'] = "Incorrect invoice number %s"%(invoice_no,)
                return render(request, 'books/book_logs_add.html', context)
                context['form'] = book_log_form
                return render(request, 'books/book_logs_add.html', context)


        book_log = book_log_form.save(commit=False)
        book_log.parent_book = book
        if invoice:
            book_log.associated_invoice = invoice
        book_log.save()

        book.current_balance = book.current_balance + book_log.change
        book.last_log = book_log
        book.save()
        recalculate_book_current_balance(book)
        return redirect('book_logs', book.id)

    return render(request, 'books/book_logs_add.html', context)

@login_required
def book_logs_del(request, booklog_id):
    bklg = get_object_or_404(BookLog, id=booklog_id)
    book = get_object_or_404(Book, id=bklg.parent_book.id, user=request.user)
    bklg.delete()
    new_total = BookLog.objects.filter(parent_book=book, is_active=True).aggregate(Sum('change'))['change__sum']
    new_last_log = BookLog.objects.filter(parent_book=book, is_active=True).last()
    if not new_total:
        new_total = 0
    book.current_balance = new_total
    book.last_log = new_last_log
    book.save()
    return redirect('book_logs', book.id)

# ================= Full Books Views ===========================
@login_required
def book_logs_full(request):
    context = {}
    # Only get totals for the summary cards, not all records
    book_logs_queryset = BookLog.objects.filter(parent_book__isnull=False, parent_book__user=request.user)
    
    # Aggregate totals by change_type in a single query
    totals = book_logs_queryset.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )

    # Fill in context with totals, using 0 if None
    total_purchased = totals['total_purchased'] or 0
    total_paid = totals['total_paid'] or 0
    total_returned = totals['total_returned'] or 0
    total_others = totals['total_others'] or 0
    total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
    
    context['total_balance'] = total_balance
    context['total_balance_word'] = num2words.num2words(abs(int(context['total_balance'])), lang='en_IN').title()
    context['total_purchased'] = abs(total_purchased)
    context['total_paid'] = abs(total_paid)
    context['total_returned'] = abs(total_returned)
    context['total_others'] = abs(total_others)
    
    return render(request, 'books/book_logs_full.html', context)

@login_required
def book_logs_full_ajax(request):
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
        
        # Filter by change_type if provided
        change_type_filter = request.GET.get('change_type', 'all')
        
        # Date range filters
        date_filter = request.GET.get('date_filter', 'all')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        
        # Base queryset
        queryset = BookLog.objects.filter(
            parent_book__isnull=False,
            parent_book__user=request.user
        ).select_related('parent_book__customer', 'associated_invoice')
        
        # Apply change_type filter
        if change_type_filter and change_type_filter != 'all':
            try:
                queryset = queryset.filter(change_type=int(change_type_filter))
            except (ValueError, TypeError):
                pass
        
        # Apply date filters
        if date_filter and date_filter != 'all':
            if date_filter == 'today':
                today = timezone.now().date()
                queryset = queryset.filter(date__date=today)
            elif date_filter == 'week':
                week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
                queryset = queryset.filter(date__date__gte=week_start)
            elif date_filter == 'month':
                month_start = timezone.now().date().replace(day=1)
                queryset = queryset.filter(date__date__gte=month_start)
            elif date_filter == 'custom' and start_date and end_date:
                try:
                    queryset = queryset.filter(date__date__gte=start_date, date__date__lte=end_date)
                except:
                    pass
        
        # Apply search filter
        if search_value:
            queryset = queryset.filter(
                Q(description__icontains=search_value) |
                Q(parent_book__customer__customer_name__icontains=search_value) |
                Q(change__icontains=search_value)
            )
        
        # Total records (before filtering)
        total_records = BookLog.objects.filter(
            parent_book__isnull=False,
            parent_book__user=request.user
        ).count()
        
        # Filtered records count
        filtered_records = queryset.count()
        
        # Calculate filtered totals before pagination
        filtered_totals = queryset.aggregate(
            total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
            total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
            total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
            total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
        )
        
        total_purchased = abs(filtered_totals['total_purchased'] or 0)
        total_paid = abs(filtered_totals['total_paid'] or 0)
        total_returned = abs(filtered_totals['total_returned'] or 0)
        total_others = abs(filtered_totals['total_others'] or 0)
        total_balance = total_purchased - (total_paid + total_returned + total_others)
        total_balance_word = num2words.num2words(abs(int(total_balance)), lang='en_IN').title()
        
        # Ordering
        order_columns = ['date', 'change_type', 'change', 'description', 'parent_book__customer__customer_name']
        if 0 <= order_column_index < len(order_columns):
            order_by = order_columns[order_column_index]
            if order_direction == 'desc':
                order_by = '-' + order_by
            queryset = queryset.order_by(order_by)
        else:
            queryset = queryset.order_by('-date')
        
        # Pagination
        queryset = queryset[start:start + length]
        
        # Prepare data
        data = []
        for item in queryset:
            # Skip if parent_book or customer is None
            if not item.parent_book or not item.parent_book.customer:
                continue
                
            # Format date
            date_str = item.date.strftime('%b %d, %Y %I:%M %p') if item.date else ''
            
            # Build actions HTML
            actions_html = '<div class="btn-group" role="group">'
            if item.associated_invoice:
                actions_html += f'<a href="/invoice/{item.associated_invoice.id}" class="btn btn-primary btn-sm btn-curve"><i class="fas fa-file-invoice"></i></a>'
            
            if item.change_type not in [1, 2]:
                actions_html += f'<a href="/book/del/{item.id}" class="btn btn-danger btn-sm btn-curve"><i class="fas fa-trash"></i></a>'
            elif not item.associated_invoice and item.change_type == 1:
                actions_html += f'<a href="/book/del/{item.id}" class="btn btn-danger btn-sm btn-curve"><i class="fas fa-trash"></i></a>'
            
            if not item.is_active:
                actions_html += f'<span class="btn btn-warning btn-sm btn-curve" onclick="markAsActive({item.id},{item.change})"><i class="fas fa-arrow-up"></i></span>'
            
            actions_html += '</div>'
            
            # Row class based on change_type
            if item.is_active and item.change_type == 0:
                row_class = 'table-success'
            elif item.is_active and item.change_type == 1:
                row_class = 'table-danger'
            elif item.is_active and item.change_type == 2:
                row_class = 'table-warning'
            elif item.is_active and item.change_type == 3:
                row_class = 'table-primary'
            else:
                row_class = 'table-secondary'
            
            customer_name = item.parent_book.customer.customer_name if item.parent_book.customer else 'Unknown Customer'
            customer_link = f'<a href="/books/{item.parent_book.id}" class="text-decoration-none text-dark">{customer_name}</a>'
            
            data.append({
                'DT_RowClass': row_class,
                'date': date_str,
                'type': item.get_change_type_display(),
                'change': str(item.change),
                'description': item.description or '',
                'customer': customer_link,
                'actions': actions_html
            })
        
        return JsonResponse({
            'draw': draw,
            'recordsTotal': total_records,
            'recordsFiltered': filtered_records,
            'data': data,
            'totals': {
                'total_purchased': total_purchased,
                'total_paid': total_paid,
                'total_returned': total_returned,
                'total_others': total_others,
                'total_balance': total_balance,
                'total_balance_word': total_balance_word
            }
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in book_logs_full_ajax: {error_details}")  # Log to console
        return JsonResponse({
            'error': str(e),
            'details': error_details
        }, status=500)

@login_required
def book_logs_full_add(request):
    context = {}
    context['form'] = BookLogFullForm(user=request.user)

    if request.method == "POST":
        book_log_form = BookLogFullForm(request.POST, user=request.user)
        if book_log_form.is_valid():
            book_log = book_log_form.save(commit=False)
            book = book_log.parent_book
            book_log.save()
            recalculate_book_current_balance(book)
            return redirect('book_logs_full')
    return render(request, 'books/book_logs_full_add.html', context)

# ================= Books API Views ===========================
@csrf_exempt
def book_logs_api_add(request):
    if request.method == "POST":
        business_uid = request.GET.get('business_uid', None)
        customer_id = request.GET.get('id', None)
        notes = request.GET.get('notes', "Added via API")
        if not business_uid or not id:
            return JsonResponse({'status': 'error', 'message': 'Business UID and Customer ID are required.'})
        user_profile = get_object_or_404(UserProfile, business_uid=business_uid)
        if user_profile:
            user = user_profile.user
        customer = get_object_or_404(Customer, customer_userid=customer_id, user=user)
        parent_book = get_object_or_404(Book, customer=customer, user=user)
        data = request.body.decode('utf-8')
        data = json.loads(data)
        inserted_count = 0
        not_inserted_count = 0
        credits = 0
        debits = 0
        for item in data:
            try:
                date_text = item.get('date') or None
                if date_text:
                    try:
                        date_text = datetime.datetime.strptime(date_text, '%Y-%m-%d')
                    except:
                        not_inserted_count += 1
                        continue
                else:
                    not_inserted_count += 1
                    continue
                changes = item.get('change') or 0
                if changes in [None, 'None', '', 0]:
                    not_inserted_count += 1
                    continue
                change = float(changes)
                if change > 0:
                    change_type = 0  # credit
                    credits += change
                else:
                    change_type = 1  # debit
                    debits += abs(change)

                associated_invoice_no = item.get('associated_invoice') or None
                associated_invoice = None
                if associated_invoice_no:
                    try:
                        associated_invoice_no = int(associated_invoice_no)
                        associated_invoice = Invoice.objects.get(user=user, invoice_number=associated_invoice_no)
                    except:
                        pass
                description = notes

                book_log = BookLog(
                    parent_book=parent_book,
                    date=date_text,
                    change=change,
                    change_type=change_type,
                    associated_invoice=associated_invoice,
                    description=description
                )
                book_log.save()
                inserted_count += 1
            except Exception as e:
                not_inserted_count += 1
        recalculate_book_current_balance(parent_book)
        return JsonResponse({'status': 'success', 'message': f'{customer.customer_name}\n{inserted_count} Book logs added successfully.\n{not_inserted_count} Book logs not added.\nCredits: {credits}, Debits: {debits}.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add book logs.'})

@csrf_exempt
def book_logs_api_active(request):
    booklog_id = request.GET.get('booklog', None)
    change = request.GET.get('change', None)
    booklog = get_object_or_404(BookLog, id=booklog_id)
    booklog.is_active = True
    booklog.save()
    recalculate_book_current_balance(booklog.parent_book)
    return JsonResponse({'status': 'success', 'message': f'Book log ID {booklog_id} marked as active. Change: ₹{change} Updated.'})

@login_required
def customerBookFilter(request):
    books = Book.objects.filter(
        customer__isnull=False,
        customer__user=request.user
    ).select_related('customer').order_by('customer__customer_name')

    data = []
    for book in books:
        data.append({
            "id": book.id,
            "name": book.customer.customer_name,
            "address": book.customer.customer_address,
            "phone": book.customer.customer_phone,
            "gstin": book.customer.customer_gst
        })

    return JsonResponse(data, safe=False)

@csrf_exempt
def book_logs_pending(request):
    if request.method == "POST":
        booklog_id = request.POST["booklog_id"]
        booklog_change = request.POST["booklog_change"]
        booklog_options = request.POST["booklog_options"]
        booklog_description = request.POST["booklog_description"]
        booklog = get_object_or_404(BookLog, id=booklog_id)
        if int(booklog_options) == 0:
            booklog.change_type = 0
            booklog.save()
        else:
            book_logs_new = BookLog(
                parent_book = booklog.parent_book,
                change_type = 3,
                change = booklog_change,
                description = booklog_description
            )
            book_logs_new.save()
        recalculate_book_current_balance(booklog.parent_book)
        return JsonResponse({'status': 'success', 'message': f'Book log ID {booklog_id} processed successfully.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add products alert stock.'})