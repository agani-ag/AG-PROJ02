# Django imports
from django.forms import FloatField
from django.utils import timezone
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, render
from django.db.models import (
    Sum, Case, When, FloatField, IntegerField,
    F,Q, CharField, Min, Max, Count, ExpressionWrapper
)
from django.db.models.functions import (
    Abs, Cast
)
# Models
from ...models import (
    Customer, UserProfile, Invoice,
    Book, BookLog, ExpenseTracker, Product,
    PurchaseLog, VendorPurchase, Inventory,
    InventoryLog
)

# Python imports
import json
import num2words
from urllib.parse import urlencode

# Utility functions
from ...utils import (
    parse_code_GS
)

# ================= Customer =============================
def customer_profile(request):
    context = {}
    cid = request.GET.get('cid', None)
    if not cid:
        return render(request, 'mobile_v1/customer/profile.html', {
            'error': 'Invalid customer link'
        })
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/profile.html', {
            'error': 'Invalid customer data'
        })
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    try:
        user = get_object_or_404(UserProfile, user__id=user_id)
        context['users'] = user
        customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)
        context['customer'] = customer
    except:
        pass
    return render(request, 'mobile_v1/customer/profile.html', context)

def customer_invoices(request):
    context = {}

    cid = request.GET.get('cid')
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page')

    if not cid:
        return render(request, 'mobile_v1/customer/invoices.html', context)

    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/invoices.html', context)

    customer_id = cid_data.get('C')
    user_id = cid_data.get('GS')

    user = get_object_or_404(UserProfile, user__id=user_id)
    customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)

    invoices_qs = Invoice.objects.filter(
        user__id=user_id,
        invoice_customer__id=customer_id
    )

    if search:
        invoices_qs = invoices_qs.filter(
            Q(invoice_number__icontains=search) |
            Q(invoice_date__icontains=search)
        )

    invoices_qs = invoices_qs.order_by('-invoice_date')

    paginator = Paginator(invoices_qs, 7)
    invoices = paginator.get_page(page_number)

    # Add the invoice_total_amt_with_gst to each invoice object
    for invoice in invoices:
        # assuming invoice_json is stored as a JSON string
        if isinstance(invoice.invoice_json, str):
            invoice_data = json.loads(invoice.invoice_json)
        else:
            invoice_data = invoice.invoice_json  # if it's already a dict
        invoice.total_amt_with_gst = invoice_data.get('invoice_total_amt_with_gst', 0)
    
    context.update({
        'users': user,
        'customer': customer,
        'invoices': invoices,
        'invoices_count': paginator.count,
        'search': search,
    })

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            'mobile_v1/customer/partials/invoice_list.html',
            context,
            request=request
        )
        return JsonResponse({'html': html})

    return render(request, 'mobile_v1/customer/invoices.html', context)

def customer_books(request):
    context = {}

    cid = request.GET.get('cid')
    filter_page = request.GET.get('filter_page')
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page')

    if not cid:
        return render(request, 'mobile_v1/customer/books.html', context)

    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/books.html', context)

    customer_id = cid_data.get('C')
    user_id = cid_data.get('GS')

    user = get_object_or_404(UserProfile, user__id=user_id)
    customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)

    books_qs = BookLog.objects.filter(
        parent_book__user__id=user_id,
        parent_book__customer__id=customer_id,
    )

    if filter_page == 'payments':
        books_qs = books_qs.filter(change_type=0)
    elif filter_page == 'purchases':
        books_qs = books_qs.filter(change_type=1)
    elif filter_page == 'returns':
        books_qs = books_qs.filter(change_type=2)
    elif filter_page == 'others':
        books_qs = books_qs.filter(change_type=3)
    elif filter_page == 'current_month_payments':
        now = timezone.now()
        books_qs = books_qs.filter(
            change_type=0,
            date__year=now.year,
            date__month=now.month
        )
    elif filter_page == 'current_month_purchases':
        now = timezone.now()
        books_qs = books_qs.filter(
            change_type=1,
            date__year=now.year,
            date__month=now.month
        )
    elif filter_page == 'last_month_payments':
        now = timezone.now()
        last_month = now.month - 1 if now.month > 1 else 12
        last_month_year = now.year if now.month > 1 else now.year - 1
        books_qs = books_qs.filter(
            change_type=0,
            date__year=last_month_year,
            date__month=last_month
        )
    elif filter_page == 'last_month_purchases':
        now = timezone.now()
        last_month = now.month - 1 if now.month > 1 else 12
        last_month_year = now.year if now.month > 1 else now.year - 1
        books_qs = books_qs.filter(
            change_type=1,
            date__year=last_month_year,
            date__month=last_month
        )



    if search:
        books_qs = books_qs.annotate(
            change_str=Cast('change', output_field=CharField()),
        ).filter(
            Q(description__icontains=search) |
            Q(createdby__icontains=search) |
            Q(change_str__icontains=search)
        )

    books_qs = books_qs.order_by('-date')

    paginator = Paginator(books_qs, 4)
    books = paginator.get_page(page_number)

    context.update({
        'users': user,
        'customer': customer,
        'books': books,
        'books_count': paginator.count,
        'search': search,
    })

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            'mobile_v1/customer/partials/book_list.html',
            context,
            request=request
        )
        return JsonResponse({'html': html})

    return render(request, 'mobile_v1/customer/books.html', context)

def customer_home(request):
    context = {}

    cid = request.GET.get('cid')
    search = request.GET.get('search', '').strip()
    page_number = request.GET.get('page')

    if not cid:
        return render(request, 'mobile_v1/customer/home.html', context)

    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/home.html', context)

    customer_id = cid_data.get('C')
    user_id = cid_data.get('GS')

    user = get_object_or_404(UserProfile, user__id=user_id)
    customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)
    context.update({
        'users': user,
        'customer': customer
    })

    now = timezone.now()
    # Calculate last month and year
    if now.month == 1:
        last_month = 12
        year = now.year - 1
    else:
        last_month = now.month - 1
        year = now.year
    # Format as MM/YYYY
    context['total_last_month_name'] = f"{last_month:02d}/{year}"
    years = BookLog.objects.filter(
        parent_book__user__id=user_id,
        parent_book__customer__id=customer_id,
        is_active=True
    ).aggregate(min_year=Min('date__year'),max_year=Max('date__year'))
    if years['min_year'] == years['max_year']:
        context['start_end_year'] = f"{years['min_year']}"
    else:
        context['start_end_year'] = f"{years['min_year']} - {years['max_year']}"
    
    book_logs = BookLog.objects.filter(
        parent_book__user__id=user_id,
        parent_book__customer__id=customer_id,
        is_active=True
    ).order_by('-date')

    totals = book_logs.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
        paid_count=Count(Case(When(change_type=0, then=1), output_field=IntegerField())),
        purchased_count=Count(Case(When(change_type=1, then=1), output_field=IntegerField())),
        returned_count=Count(Case(When(change_type=2, then=1), output_field=IntegerField())),
        others_count=Count(Case(When(change_type=3, then=1), output_field=IntegerField())),
    )
    overall_payment_percentage = 0
    if totals['total_purchased'] and totals['total_purchased'] != 0:
        overall_payment_percentage = (abs(totals['total_paid'] or 0) / abs(totals['total_purchased'])) * 100
    context['overall_payment_percentage'] = int(overall_payment_percentage)    
    # Fill in context with totals, using 0 if None
    total_purchased = totals['total_purchased'] or 0
    total_paid = totals['total_paid'] or 0
    total_returned = totals['total_returned'] or 0
    total_others = totals['total_others'] or 0
    # total_balance = abs(total_purchased) - abs(total_paid)
    total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
    # Counts
    context['purchased_count'] = totals['purchased_count'] or 0
    context['paid_count'] = totals['paid_count'] or 0
    context['returned_count'] = totals['returned_count'] or 0
    context['others_count'] = totals['others_count'] or 0
    # Calculate balance (absolute value if you want it always positive)
    context['total_balance'] = total_balance
    context['total_purchased'] = abs(total_purchased)
    context['total_paid'] = abs(total_paid)
    context['total_returned'] = abs(total_returned)
    context['total_others'] = abs(total_others)

    # Current Month Totals
    current_year = now.year
    current_month = now.month
    # Filter logs for current month
    current_month_book_logs = BookLog.objects.filter(
        parent_book__user__id=user_id,
        parent_book__customer__id=customer_id,
        is_active=True,
        date__year=current_year,
        date__month=current_month
    ).order_by('-date')
    current_month_totals = current_month_book_logs.aggregate(
        current_month_total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        current_month_total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        current_month_paid_count=Count(Case(When(change_type=0, then=1), output_field=IntegerField())),
        current_month_purchased_count=Count(Case(When(change_type=1, then=1), output_field=IntegerField())),
    )
    current_month_payment_percentage = 0
    if current_month_totals['current_month_total_purchased'] and current_month_totals['current_month_total_purchased'] != 0:
        current_month_payment_percentage = (abs(current_month_totals['current_month_total_paid'] or 0) / abs(current_month_totals['current_month_total_purchased'])) * 100
    context['current_month_payment_percentage'] = int(current_month_payment_percentage)
    current_month_total_purchased = current_month_totals['current_month_total_purchased'] or 0
    current_month_total_paid = current_month_totals['current_month_total_paid'] or 0
    current_month_paid_count = current_month_totals['current_month_paid_count'] or 0
    current_month_purchased_count = current_month_totals['current_month_purchased_count'] or 0
    context['current_month_total_purchased'] = abs(int(current_month_total_purchased))
    context['current_month_total_paid'] = abs(int(current_month_total_paid))
    context['current_month_paid_count'] = abs(int(current_month_paid_count))
    context['current_month_purchased_count'] = abs(int(current_month_purchased_count))
    
    # Last Month Totals
    current_year = now.year
    last_month = now.month - 1 if now.month > 1 else 12
    last_month_year = current_year if now.month > 1 else current_year - 1
    # Filter logs for last month
    last_month_book_logs = BookLog.objects.filter(
        parent_book__user__id=user_id,
        parent_book__customer__id=customer_id,
        is_active=True,
        date__year=last_month_year,
        date__month=last_month
    ).order_by('-date')
    last_month_totals = last_month_book_logs.aggregate(
        last_month_total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        last_month_total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        last_month_paid_count=Count(Case(When(change_type=0, then=1), output_field=IntegerField())),
        last_month_purchased_count=Count(Case(When(change_type=1, then=1), output_field=IntegerField())),
    )
    last_month_payment_percentage = 0
    if last_month_totals['last_month_total_purchased'] and last_month_totals['last_month_total_purchased'] != 0:
        last_month_payment_percentage = (abs(last_month_totals['last_month_total_paid'] or 0) / abs(last_month_totals['last_month_total_purchased'])) * 100
    context['last_month_payment_percentage'] = int(last_month_payment_percentage)
    last_month_total_purchased = last_month_totals['last_month_total_purchased'] or 0
    last_month_total_paid = last_month_totals['last_month_total_paid'] or 0
    last_month_paid_count = last_month_totals['last_month_paid_count'] or 0
    last_month_purchased_count = last_month_totals['last_month_purchased_count'] or 0
    context['last_month_total_purchased'] = abs(int(last_month_total_purchased))
    context['last_month_total_paid'] = abs(int(last_month_total_paid))
    context['last_month_paid_count'] = abs(int(last_month_paid_count))
    context['last_month_purchased_count'] = abs(int(last_month_purchased_count))
    # Overdue
    only_purchases = only_purchases = book_logs.filter(change_type=1).annotate(amount_positive=Abs('change')).order_by('date')
    remaining_amount = abs(total_paid) + abs(total_returned) + abs(total_others)
    show_90_only = request.GET.get('overdue') == '90'
    filtered_logs = []
    payment_failed = False
    for log in only_purchases:
        # overdue days
        log.overdue_days = (now - log.date).days if log.date else 0
        invoice_amount = log.amount_positive

        if not payment_failed and remaining_amount >= invoice_amount:
            # covered
            remaining_amount -= invoice_amount
            continue

        # once failed, everything is overdue
        payment_failed = True
        log.remaining_amount = remaining_amount
        log.balance_after = abs(remaining_amount - invoice_amount)
        log.payment_pending = True
        if show_90_only and log.overdue_days < 90:
            continue
        filtered_logs.append(log)

    params = request.GET.copy()
    params_overdue_90 = params.copy()
    params_overdue_90['overdue'] = '90'
    params_show_all = params.copy()
    params_show_all.pop('overdue', None)
    context['url_overdue_90'] = f"?{urlencode(params_overdue_90)}"
    context['url_show_all'] = f"?{urlencode(params_show_all)}"
    context['show_90_only'] = show_90_only
    context['overdue_logs'] = filtered_logs
    return render(request, 'mobile_v1/customer/home.html', context)

def customer_invoice_viewer(request, invoice_id):
    context = {}
    cid = request.GET.get('cid')

    if not cid:
        return render(request, 'mobile_v1/customer/invoice_printer.html', context)

    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/invoice_printer.html', context)
    
    customer_id = cid_data.get('C')
    user_id = cid_data.get('GS')
    try:
        invoice_obj = get_object_or_404(Invoice, user__id=user_id, id=invoice_id)
        user_profile = get_object_or_404(UserProfile, user__id=user_id)
    except:
        return render(request, 'mobile_v1/customer/invoice_printer.html', context)

    context['invoice'] = invoice_obj
    context['invoice_data'] = json.loads(invoice_obj.invoice_json)
    context['currency'] = "₹"
    context['total_in_words'] = num2words.num2words(int(context['invoice_data']['invoice_total_amt_with_gst']), lang='en_IN').title()
    context['user_profile'] = user_profile
    return render(request, 'mobile_v1/customer/invoice_printer.html', context)

def customers(request):
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from django.db.models import Q, Count
    
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Base querysets
    users = UserProfile.objects.all().order_by('business_title')
    customers_qs = Customer.objects.select_related('user').order_by('customer_name')
    
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        customers_qs = customers_qs.filter(user__id__in=user_ids)

    # Apply user filter
    if user_id and user_id.isdigit():
        customers_qs = customers_qs.filter(user__id=int(user_id))
    # Apply search filter
    if search_query:
        customers_qs = customers_qs.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(customer_gst__icontains=search_query) |
            Q(customer_email__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(customers_qs, 20)
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals
    total_count = customers_qs.count()
    
    # Get customer counts per user
    user_customer_counts = Customer.objects.values('user__id').annotate(
        count=Count('id')
    )
    user_counts_dict = {item['user__id']: item['count'] for item in user_customer_counts}
    
    # Add counts to users
    for user in users:
        user.customer_count = user_counts_dict.get(user.user.id, 0)
    
    context.update({
        'users': users,
        'page_obj': page_obj,
        'total_count': total_count,
        'current_user_id': user_id,
        'current_search': search_query,
        'users_filter': users_filter,
    })
    
    # AJAX request - return JSON with HTML
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/customer_list.html', context, request=request)
        return JsonResponse({
            'html': html,
            'total_count': total_count,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/customers.html', context)

def invoices(request):
    import json
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from django.db.models import Q
    from datetime import datetime, timedelta
    
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    customer_id = request.GET.get('customer_id', '')
    search_query = request.GET.get('search', '').strip()
    date_filter = request.GET.get('date_filter', 'all')
    gst_filter = request.GET.get('gst_filter', 'all')
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Base querysets
    users = UserProfile.objects.all().order_by('business_title')
    customers = Customer.objects.all().order_by('customer_name')
    invoices_qs = Invoice.objects.select_related('user', 'invoice_customer').order_by('-invoice_date', '-invoice_number')
    
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        invoices_qs = invoices_qs.filter(user__id__in=user_ids)
        customers = customers.filter(user__id__in=user_ids)

    # Apply user filter
    if user_id and user_id.isdigit():
        invoices_qs = invoices_qs.filter(user__id=int(user_id))
        customers = customers.filter(user__id=int(user_id))
    
    # Apply customer filter
    if customer_id and customer_id.isdigit():
        invoices_qs = invoices_qs.filter(invoice_customer__id=int(customer_id))
    
    # Apply GST filter
    if gst_filter == 'gst':
        invoices_qs = invoices_qs.filter(is_gst=True)
    elif gst_filter == 'non-gst':
        invoices_qs = invoices_qs.filter(is_gst=False)
    
    # Apply date filter
    today = datetime.now().date()
    if date_filter == 'today':
        invoices_qs = invoices_qs.filter(invoice_date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        invoices_qs = invoices_qs.filter(invoice_date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        invoices_qs = invoices_qs.filter(invoice_date__gte=month_ago)
    
    # Apply search filter
    if search_query:
        invoices_qs = invoices_qs.filter(
            Q(invoice_number__icontains=search_query) |
            Q(invoice_customer__customer_name__icontains=search_query) |
            Q(invoice_customer__customer_phone__icontains=search_query)
        )
    
    # Add invoice amounts
    invoices_with_amounts = []
    for invoice in invoices_qs:
        try:
            invoice_data = json.loads(invoice.invoice_json)
            invoice.amount = invoice_data.get('invoice_total_amt_with_gst', 0)
        except:
            invoice.amount = 0
        invoices_with_amounts.append(invoice)
    
    # Pagination
    paginator = Paginator(invoices_with_amounts, 15)
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals for current filtered results
    total_amount = sum(inv.amount for inv in invoices_with_amounts)
    total_count = len(invoices_with_amounts)
    
    context.update({
        'users': users,
        'customers': customers,
        'page_obj': page_obj,
        'total_amount': total_amount,
        'total_count': total_count,
        'current_user_id': user_id,
        'current_customer_id': customer_id,
        'current_search': search_query,
        'current_date_filter': date_filter,
        'current_gst_filter': gst_filter,
        'users_filter': users_filter,
    })
    
    # AJAX request - return JSON with HTML
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/invoice_list.html', context, request=request)
        return JsonResponse({
            'html': html,
            'total_count': total_count,
            'total_amount': total_amount,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/invoices.html', context)


def books(request):
    """Books listing with filtering, search, and pagination"""
    from datetime import datetime, timedelta
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    customer_id = request.GET.get('customer_id', '')
    search_query = request.GET.get('search', '').strip()
    filter_type = request.GET.get('filter_type', 'all')  # all, payments, purchases, returns, others
    status_filter = request.GET.get('status_filter', 'active')  # active, inactive, all
    date_filter = request.GET.get('date_filter', 'all')  # all, today, week, month, custom
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user')
    
    # Base queryset
    books_qs = BookLog.objects.select_related(
        'parent_book__customer',
        'parent_book__user'
    )
    
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        books_qs = books_qs.filter(parent_book__user__id__in=user_ids)
    
    # Apply status filter
    if status_filter == 'active':
        books_qs = books_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        books_qs = books_qs.filter(is_active=False)
    # else: show all (no filter)
    
    # Apply user filter
    if user_id:
        books_qs = books_qs.filter(parent_book__user__id=user_id)
    
    # Apply customer filter
    if customer_id:
        books_qs = books_qs.filter(parent_book__customer__id=customer_id)
    
    # Apply filter type
    if filter_type == 'payments':
        books_qs = books_qs.filter(change_type=0)
    elif filter_type == 'purchases':
        books_qs = books_qs.filter(change_type=1)
    elif filter_type == 'returns':
        books_qs = books_qs.filter(change_type=2)
    elif filter_type == 'pending':
        books_qs = books_qs.filter(change_type=4)
    elif filter_type == 'others':
        books_qs = books_qs.filter(change_type=3)
    
    # Apply search
    if search_query:
        books_qs = books_qs.filter(
            Q(parent_book__customer__customer_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(change__icontains=search_query)
        )
    
    # Apply date filter
    today = datetime.now().date()
    if date_filter == 'today':
        books_qs = books_qs.filter(date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        books_qs = books_qs.filter(date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        books_qs = books_qs.filter(date__gte=month_ago)
    elif date_filter == 'custom' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            books_qs = books_qs.filter(date__gte=start, date__lte=end)
        except ValueError:
            pass  # Invalid date format, ignore
    
    # Order by date
    books_qs = books_qs.order_by('-date')
    
    # Get all customers for dropdown (filtered by user if selected)
    if user_id:
        customers = Customer.objects.filter(user__id=user_id).order_by('customer_name')
    else:
        customers = Customer.objects.all().order_by('customer_name')
    
    # Pagination
    paginator = Paginator(books_qs, 15)  # 15 items per page
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals only for active entries
    totals_qs = BookLog.objects.select_related(
        'parent_book__customer',
        'parent_book__user'
    ).filter(is_active=True)
    
    # Apply users filter
    if users_filter:
        totals_qs = totals_qs.filter(parent_book__user__id__in=user_ids)

    # Apply same filters for totals calculation
    if user_id:
        totals_qs = totals_qs.filter(parent_book__user__id=user_id)
    if customer_id:
        totals_qs = totals_qs.filter(parent_book__customer__id=customer_id)
    if search_query:
        totals_qs = totals_qs.filter(
            Q(parent_book__customer__customer_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(change__icontains=search_query)
        )
    # Apply date filter to totals
    if date_filter == 'today':
        totals_qs = totals_qs.filter(date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        totals_qs = totals_qs.filter(date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        totals_qs = totals_qs.filter(date__gte=month_ago)
    elif date_filter == 'custom' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            totals_qs = totals_qs.filter(date__gte=start, date__lte=end)
        except ValueError:
            pass
    
    # Calculate totals for current filter (only active)
    totals = totals_qs.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )
    
    # Calculate balance
    total_purchased = abs(totals['total_purchased'] or 0)
    total_paid = abs(totals['total_paid'] or 0)
    total_returned = abs(totals['total_returned'] or 0)
    total_others = abs(totals['total_others'] or 0)
    # total_balance = total_purchased - total_paid
    total_balance = total_purchased - (total_paid + total_returned + total_others)
    
    context.update({
        'users': users,
        'customers': customers,
        'page_obj': page_obj,
        'total_count': paginator.count,
        'current_user_id': user_id,
        'current_customer_id': customer_id,
        'current_search': search_query,
        'current_filter_type': filter_type,
        'current_status_filter': status_filter,
        'current_date_filter': date_filter,
        'current_start_date': start_date,
        'current_end_date': end_date,
        'total_purchased': total_purchased,
        'total_paid': total_paid,
        'total_returned': total_returned,
        'total_others': total_others,
        'total_balance': total_balance,
        'users_filter': users_filter,
    })
    
    # AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/book_list.html', context, request=request)
        return JsonResponse({
            'html': html,
            'total_count': paginator.count,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'total_purchased': total_purchased,
            'total_paid': total_paid,
            'total_returned': total_returned,
            'total_others': total_others,
            'total_balance': total_balance,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/books.html', context)

def customersapi(request):
    customers = Customer.objects.all().values(
        business_name=F('customer_name'),
        brand_name=F('user__userprofile__business_brand'),
        name=F('customer_userid'),
        password=F('customer_password'),
        gst=F('customer_gst')
    ).exclude(customer_userid__isnull=True).exclude(customer_userid='') \
     .exclude(customer_password__isnull=True).exclude(customer_password='')\
     .exclude(is_mobile_user=False)

    # Collect all links per GST
    gst_map = {}

    for customer in customers:
        gst = customer['gst']
        userid = customer['name']
        brand_name = customer['brand_name']

        link_obj = {
            "name": brand_name,
            "link": f"/mobile/v1/customer/home?cid={userid}"
        }

        if gst not in gst_map:
            gst_map[gst] = []

        if link_obj not in gst_map[gst]:
            gst_map[gst].append(link_obj)

    # Build final response
    customers_dict = {}

    for customer in customers:
        name = customer['name']
        gst = customer['gst']
        links = gst_map.get(gst, [])

        customers_dict[name] = {
            'business_name': customer['business_name'],
            'name': name,
            'password': customer['password'],
            'deflink': f"/mobile/v1/customer/home?cid={name}",
            'linklist': links if len(links) > 1 else []
        }

    return JsonResponse(customers_dict, safe=False)

def customers_book_add_api(request):
    context = {}
    cid = request.GET.get('cid')
    if not cid:
        return JsonResponse({'status': 'error', 'message': 'Try again later.'})
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return JsonResponse({'status': 'error', 'message': 'Try again later.'})
    customer_id = cid_data.get('C')
    user_id = cid_data.get('GS')
    user = get_object_or_404(UserProfile, user__id=user_id)
    customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)
    parent_book = parent_book = get_object_or_404(Book, customer=customer, user=user.user)
    if request.method == 'POST':
        change_amount = request.POST.get('change_amount')
        description = request.POST.get('description', '').strip()
        if description == 'Cheque':
            change_type = 4  # pending
        else:
            change_type = 0  # payment
        try:
            book_log = BookLog(
                parent_book=parent_book,
                change_type=change_type,
                change=float(change_amount),
                description=description,
                createdby=customer.customer_name + ' via Mobile App',
                is_active=False,  # default to inactive until verified
            )
            book_log.save()

            return JsonResponse({'status': 'success', 'message': 'Payment added successfully.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Try again later.'})

def customers_reset_password_api(request):
    cid = request.GET.get('cid')
    if not cid:
        return JsonResponse({'status': 'error', 'message': 'Try again later.'})
    customer = get_object_or_404(Customer, customer_userid=cid)
    customers = Customer.objects.filter(
        customer_gst=customer.customer_gst,
        is_mobile_user=True
    )
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        if not new_password:
            return JsonResponse({'status': 'error', 'message': 'Password cannot be empty.'})
        try:
            for customer in customers:
                customer.customer_password = new_password
                customer.is_mobile_user = True
                customer.save()
            return JsonResponse({'status': 'success', 'message': 'Password reset successfully.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Try again later.'})

def expenses_tracker(request):
    """Expense Tracker listing with filtering, search, and pagination"""
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from django.db.models import Q, Sum
    from datetime import datetime, timedelta
    
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    search_query = request.GET.get('search', '').strip()
    category_filter = request.GET.get('category', 'all')
    date_filter = request.GET.get('date_filter', 'all')
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user').order_by('business_title')
    
    # Base queryset
    expenses_qs = ExpenseTracker.objects.select_related('user').order_by('-date')
    
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        expenses_qs = expenses_qs.filter(user__id__in=user_ids)

    # Apply user filter
    if user_id:
        expenses_qs = expenses_qs.filter(user__id=user_id)
    
    # Apply date filter
    today = datetime.now().date()
    if date_filter == 'today':
        expenses_qs = expenses_qs.filter(date__date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        expenses_qs = expenses_qs.filter(date__date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        expenses_qs = expenses_qs.filter(date__date__gte=month_ago)
    
    # Get all categories for the selected user
    if user_id:
        categories = ExpenseTracker.objects.filter(user__id=user_id).values_list('category', flat=True).distinct().order_by('category')
    else:
        if users_filter:
            categories = ExpenseTracker.objects.filter(user__id__in=user_ids).values_list('category', flat=True).distinct().order_by('category')
        else:
            categories = ExpenseTracker.objects.values_list('category', flat=True).distinct().order_by('category')
    
    # Apply category filter
    if category_filter != 'all':
        expenses_qs = expenses_qs.filter(category=category_filter)
    
    # Apply search filter
    if search_query:
        expenses_qs = expenses_qs.filter(
            Q(reference__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(amount__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(expenses_qs, 15)  # 15 items per page
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals for current filter
    totals = expenses_qs.aggregate(
        total_amount=Sum('amount')
    )
    
    total_amount = abs(totals['total_amount'] or 0)
    total_count = paginator.count
    
    context.update({
        'users': users,
        'categories': categories,
        'page_obj': page_obj,
        'total_amount': total_amount,
        'total_count': total_count,
        'current_user_id': user_id,
        'current_search': search_query,
        'current_category': category_filter,
        'current_date_filter': date_filter,
        'users_filter': users_filter,
    })
    
    # AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/expense_list.html', context, request=request)
        return JsonResponse({
            'html': html,
            'total_count': total_count,
            'total_amount': float(total_amount),
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/expenses_tracker.html', context)

def purchase_logs(request):
    """Purchase Logs listing with filtering, search, and pagination"""
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from django.db.models import Q, Sum
    from datetime import datetime, timedelta
    from ...models import PurchaseLog, VendorPurchase
    
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    vendor_id = request.GET.get('vendor_id', '')
    search_query = request.GET.get('search', '').strip()
    category_filter = request.GET.get('category', 'all')
    type_filter = request.GET.get('type_filter', 'all')  # all, purchase, paid, others
    date_filter = request.GET.get('date_filter', 'all')
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user').order_by('business_title')
    
    # Base queryset
    purchases_qs = PurchaseLog.objects.select_related('user', 'vendor').order_by('-date')
    
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
        purchases_qs = purchases_qs.filter(user__id__in=user_ids)

    # Apply user filter
    if user_id:
        purchases_qs = purchases_qs.filter(user__id=user_id)
    
    # Apply vendor filter
    if vendor_id:
        purchases_qs = purchases_qs.filter(vendor__id=vendor_id)
    
    # Apply type filter
    if type_filter == 'purchase':
        purchases_qs = purchases_qs.filter(change_type=0)
    elif type_filter == 'paid':
        purchases_qs = purchases_qs.filter(change_type=1)
    elif type_filter == 'others':
        purchases_qs = purchases_qs.filter(change_type=3)
    
    # Apply date filter
    today = datetime.now().date()
    if date_filter == 'today':
        purchases_qs = purchases_qs.filter(date__date=today)
    elif date_filter == 'week':
        week_ago = today - timedelta(days=7)
        purchases_qs = purchases_qs.filter(date__date__gte=week_ago)
    elif date_filter == 'month':
        month_ago = today - timedelta(days=30)
        purchases_qs = purchases_qs.filter(date__date__gte=month_ago)
    
    # Get all categories and vendors for the selected user
    if user_id:
        categories = PurchaseLog.objects.filter(user__id=user_id).values_list('category', flat=True).distinct().order_by('category')
        vendors = VendorPurchase.objects.filter(user__id=user_id).order_by('vendor_name')
    else:
        if users_filter:
            categories = PurchaseLog.objects.filter(user__id__in=user_ids).values_list('category', flat=True).distinct().order_by('category')
            vendors = VendorPurchase.objects.filter(user__id__in=user_ids).order_by('vendor_name')
        else:
            categories = PurchaseLog.objects.values_list('category', flat=True).distinct().order_by('category')
            vendors = VendorPurchase.objects.all().order_by('vendor_name')
    
    # Apply category filter
    if category_filter != 'all':
        purchases_qs = purchases_qs.filter(category=category_filter)
    
    # Apply search filter
    if search_query:
        purchases_qs = purchases_qs.filter(
            Q(reference__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(vendor__vendor_name__icontains=search_query) |
            Q(change__icontains=search_query)
        )
    
    # Pagination
    paginator = Paginator(purchases_qs, 15)  # 15 items per page
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals for current filter
    totals = purchases_qs.aggregate(
        total_purchase=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_paid=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )
    
    total_purchase = abs(totals['total_purchase'] or 0)
    total_paid = abs(totals['total_paid'] or 0)
    total_balance = total_purchase - total_paid
    total_count = paginator.count
    
    context.update({
        'users': users,
        'vendors': vendors,
        'categories': categories,
        'page_obj': page_obj,
        'total_purchase': total_purchase,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'total_count': total_count,
        'current_user_id': user_id,
        'current_vendor_id': vendor_id,
        'current_search': search_query,
        'current_category': category_filter,
        'current_type_filter': type_filter,
        'current_date_filter': date_filter,
        'users_filter': users_filter,
    })
    
    # AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/purchase_list.html', context, request=request)
        return JsonResponse({
            'html': html,
            'total_count': total_count,
            'total_purchase': float(total_purchase),
            'total_paid': float(total_paid),
            'total_balance': float(total_balance),
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/purchase_log.html', context)

def products(request):
    user_id = request.GET.get('user_id', None)
    search_query = request.GET.get('search', '').strip()
    stock_filter = request.GET.get('stock_filter', 'all')  # all, in_stock, low_stock, out_of_stock
    discount_filter = request.GET.get('discount_filter', 'all')  # all, with_discount, no_discount
    hsn_filter = request.GET.get('hsn_filter', '')
    page_number = request.GET.get('page', 1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = list(map(int, users_filter.split(','))) if users_filter else []
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user')
    
    # Get distinct HSN codes
    hsn_codes = Product.objects.filter(product_hsn__isnull=False).exclude(product_hsn='').values_list('product_hsn', flat=True).distinct().order_by('product_hsn')
    
    # Filter products
    products_qs = Product.objects.all().select_related('user')
    
    # Apply users filter
    if users_filter:
        users = users.filter(user__id__in=user_ids)
        products_qs = products_qs.filter(user__id__in=user_ids)

    if user_id:
        products_qs = products_qs.filter(user__id=user_id)
    
    if user_ids:
        products_qs = products_qs.filter(user__id__in=user_ids)

    if search_query:
        products_qs = products_qs.filter(
            Q(model_no__icontains=search_query) |
            Q(product_name__icontains=search_query) |
            Q(product_hsn__icontains=search_query)
        )
    
    # HSN filter
    if hsn_filter:
        products_qs = products_qs.filter(product_hsn=hsn_filter)
    
    # Discount filter
    if discount_filter == 'with_discount':
        products_qs = products_qs.filter(product_discount__gt=0)
    elif discount_filter == 'no_discount':
        products_qs = products_qs.filter(Q(product_discount=0) | Q(product_discount__isnull=True))
    
    # Get product IDs with inventory data
    product_ids = list(products_qs.values_list('id', flat=True))
    
    # Apply stock filter
    if stock_filter == 'in_stock':
        inventory_ids = Inventory.objects.filter(product__id__in=product_ids, current_stock__gt=0).values_list('product_id', flat=True)
        products_qs = products_qs.filter(id__in=inventory_ids)
    elif stock_filter == 'low_stock':
        inventory_low = Inventory.objects.filter(product__id__in=product_ids, current_stock__gt=0, current_stock__lte=F('alert_level')).values_list('product_id', flat=True)
        products_qs = products_qs.filter(id__in=inventory_low)
    elif stock_filter == 'out_of_stock':
        inventory_out = Inventory.objects.filter(product__id__in=product_ids, current_stock=0).values_list('product_id', flat=True)
        products_qs = products_qs.filter(id__in=inventory_out)
    
    products_qs = products_qs.order_by('-id')
    
    # Pagination
    paginator = Paginator(products_qs, 15)
    products_page = paginator.get_page(page_number)
    
    # Add inventory data to products
    for product in products_page:
        try:
            inventory = Inventory.objects.get(product=product)
            product.current_stock = inventory.current_stock
            product.alert_level = inventory.alert_level
            product.is_low_stock = inventory.current_stock > 0 and inventory.current_stock <= inventory.alert_level
        except Inventory.DoesNotExist:
            product.current_stock = None
            product.alert_level = None
            product.is_low_stock = False
        
        # Calculate price breakdown for discounted products
        if product.product_discount > 0:
            # Calculate base price (remove GST from product_rate_with_gst)
            gst_multiplier = 1 + (product.product_gst_percentage / 100)
            product.base_price = product.product_rate_with_gst / gst_multiplier
            
            # Calculate discounted base price
            discount_multiplier = 1 - (product.product_discount / 100)
            product.discounted_base_price = product.base_price * discount_multiplier
            
            # Calculate final price with GST
            product.final_price_with_gst = product.discounted_base_price * gst_multiplier
    
    # Get stats
    total_products = products_qs.count()
    in_stock_count = Inventory.objects.filter(product__id__in=product_ids, current_stock__gt=0).count()
    low_stock_count = Inventory.objects.filter(product__id__in=product_ids, current_stock__gt=0, current_stock__lte=F('alert_level')).count()
    out_of_stock_count = Inventory.objects.filter(product__id__in=product_ids, current_stock=0).count()
    with_discount_count = Product.objects.filter(id__in=product_ids, product_discount__gt=0).count()
    
    context = {
        'users': users,
        'hsn_codes': hsn_codes,
        'products': products_page,
        'total_products': total_products,
        'in_stock_count': in_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'with_discount_count': with_discount_count,
        'current_user_id': user_id or '',
        'current_search': search_query,
        'current_stock_filter': stock_filter,
        'current_discount_filter': discount_filter,
        'current_hsn_filter': hsn_filter,
        'users_filter': users_filter,
    }
    
    # AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('mobile_v1/partials/product_list.html', {
            'products': products_page,
        }, request=request)
        
        return JsonResponse({
            'html': html,
            'total_count': total_products,
            'in_stock_count': in_stock_count,
            'low_stock_count': low_stock_count,
            'out_of_stock_count': out_of_stock_count,
            'with_discount_count': with_discount_count,
            'has_previous': products_page.has_previous(),
            'has_next': products_page.has_next(),
            'current_page': products_page.number,
            'total_pages': paginator.num_pages,
            'users_filter': users_filter,
        })
    
    return render(request, 'mobile_v1/products.html', context)

def home(request):
    """Admin/Employee Dashboard Home Page with comprehensive business overview"""
    from datetime import datetime, timedelta
    from django.db.models import Sum, Count
    
    context = {}
    
    # Current and last month dates
    today = datetime.now().date()
    current_month_start = today.replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    users_filter = request.GET.get('users_filter', '')
    user_ids = []
    
    # Get all users
    users = UserProfile.objects.all().select_related('user')
    # Apply users filter
    if users_filter:
        user_ids = [int(uid) for uid in users_filter.split(',') if uid.isdigit()]
        users = users.filter(user__id__in=user_ids)
    
    # Total users
    total_users = users.count()
    
    # === CURRENT MONTH STATS ===
    current_month_invoices = Invoice.objects.filter(invoice_date__gte=current_month_start)
    current_month_books = BookLog.objects.filter(date__date__gte=current_month_start)
    current_month_expenses = ExpenseTracker.objects.filter(date__date__gte=current_month_start)
    current_month_purchases = PurchaseLog.objects.filter(date__date__gte=current_month_start)
    
    if users_filter:
        current_month_invoices = current_month_invoices.filter(user__id__in=user_ids)
        current_month_books = current_month_books.filter(parent_book__user__id__in=user_ids)
        current_month_expenses = current_month_expenses.filter(user__id__in=user_ids)
        current_month_purchases = current_month_purchases.filter(user__id__in=user_ids)

    # Current month invoice count
    current_month_invoice_count = current_month_invoices.count()
    
    # Current month book log totals
    current_book_stats = current_month_books.aggregate(
        payments=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        purchases=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
    )
    current_month_purchases_amount = abs(current_book_stats['purchases'] or 0)
    current_month_payments_amount = abs(current_book_stats['payments'] or 0)
    
    # Current month expenses
    current_expense_total = current_month_expenses.aggregate(total=Sum('amount'))['total'] or 0
    current_expense_count = current_month_expenses.count()
    
    # Current month purchase logs
    current_purchase_stats = current_month_purchases.aggregate(
        total=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        count=Count(Case(When(change_type=0, then=1)))
    )
    current_month_purchase_amount = abs(current_purchase_stats['total'] or 0)
    current_month_purchase_count = current_purchase_stats['count'] or 0
    
    # === LAST MONTH STATS ===
    last_month_invoices = Invoice.objects.filter(invoice_date__gte=last_month_start, invoice_date__lt=current_month_start)
    last_month_books = BookLog.objects.filter(date__date__gte=last_month_start, date__date__lt=current_month_start)
    last_month_expenses = ExpenseTracker.objects.filter(date__date__gte=last_month_start, date__date__lt=current_month_start)
    last_month_purchases = PurchaseLog.objects.filter(date__date__gte=last_month_start, date__date__lt=current_month_start)
    
    if users_filter:
        last_month_invoices = last_month_invoices.filter(user__id__in=user_ids)
        last_month_books = last_month_books.filter(parent_book__user__id__in=user_ids)
        last_month_expenses = last_month_expenses.filter(user__id__in=user_ids)
        last_month_purchases = last_month_purchases.filter(user__id__in=user_ids)

    # Last month invoice count
    last_month_invoice_count = last_month_invoices.count()
    
    # Last month book log totals
    last_book_stats = last_month_books.aggregate(
        payments=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        purchases=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
    )
    last_month_purchases_amount = abs(last_book_stats['purchases'] or 0)
    last_month_payments_amount = abs(last_book_stats['payments'] or 0)
    
    # Last month expenses
    last_expense_total = last_month_expenses.aggregate(total=Sum('amount'))['total'] or 0
    last_expense_count = last_month_expenses.count()
    
    # === OVERALL STATS ===
    total_customers = Customer.objects.count()
    total_products = Product.objects.count()
    total_invoices = Invoice.objects.count()

    if users_filter:
        total_customers = Customer.objects.filter(user__id__in=user_ids).count()
        total_products = Product.objects.filter(user__id__in=user_ids).count()
        total_invoices = Invoice.objects.filter(user__id__in=user_ids).count()
    
    # Total book logs
    all_book_stats = BookLog.objects.aggregate(
        purchases=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        payments=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        returns=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )

    if users_filter:
        all_book_stats = BookLog.objects.filter(parent_book__user__id__in=user_ids).aggregate(
            purchases=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
            payments=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
            returns=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
            others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
        )

    total_purchases = abs(all_book_stats['purchases'] or 0)
    total_payments = abs(all_book_stats['payments'] or 0)
    total_returns = abs(all_book_stats['returns'] or 0)
    total_others = abs(all_book_stats['others'] or 0)
    total_balance = total_purchases - (total_payments + total_returns + total_others)
    
    # Total expenses
    total_expenses = ExpenseTracker.objects.aggregate(total=Sum('amount'))['total'] or 0
    total_expense_count = ExpenseTracker.objects.count()

    if users_filter:
        total_expenses = ExpenseTracker.objects.filter(user__id__in=user_ids).aggregate(total=Sum('amount'))['total'] or 0
        total_expense_count = ExpenseTracker.objects.filter(user__id__in=user_ids).count()
    
    # Inventory stats
    inventory_stats = Inventory.objects.aggregate(
        total_stock=Sum('current_stock'),
        low_stock_count=Count(Case(When(current_stock__gt=0, current_stock__lte=F('alert_level'), then=1))),
        out_of_stock_count=Count(Case(When(current_stock=0, then=1)))
    )
    if users_filter:
        inventory_stats = Inventory.objects.filter(product__user__id__in=user_ids).aggregate(
            total_stock=Sum('current_stock'),
            low_stock_count=Count(Case(When(current_stock__gt=0, current_stock__lte=F('alert_level'), then=1))),
            out_of_stock_count=Count(Case(When(current_stock=0, then=1)))
        )
    total_stock = inventory_stats['total_stock'] or 0
    low_stock_count = inventory_stats['low_stock_count'] or 0
    out_of_stock_count = inventory_stats['out_of_stock_count'] or 0
    
    # Products with discount
    discount_products = Product.objects.filter(product_discount__gt=0).count()
    if users_filter:
        discount_products = Product.objects.filter(user__id__in=user_ids, product_discount__gt=0).count()
    
    # Calculate payment progress percentages
    current_month_payment_percentage = 0
    if current_month_purchases_amount > 0:
        current_month_payment_percentage = min(100, (current_month_payments_amount / current_month_purchases_amount) * 100)
    
    last_month_payment_percentage = 0
    if last_month_purchases_amount > 0:
        last_month_payment_percentage = min(100, (last_month_payments_amount / last_month_purchases_amount) * 100)
    
    overall_payment_percentage = 0
    if total_purchases > 0:
        overall_payment_percentage = min(100, (total_payments / total_purchases) * 100)
    
    # Recent activity - last 5 invoices
    recent_invoices = Invoice.objects.select_related('invoice_customer', 'user').order_by('-invoice_date')[:5]
    if users_filter:
        recent_invoices = Invoice.objects.select_related('invoice_customer', 'user').filter(user__id__in=user_ids).order_by('-invoice_date')[:5]
    # Recent expenses - last 5
    recent_expenses = ExpenseTracker.objects.select_related('user').order_by('-date')[:5]
    if users_filter:
        recent_expenses = ExpenseTracker.objects.select_related('user').filter(user__id__in=user_ids).order_by('-date')[:5]
    context.update({
        'current_month_name': current_month_start.strftime('%B %Y'),
        'last_month_name': last_month_start.strftime('%B %Y'),
        'total_users': total_users,
        'total_customers': total_customers,
        'total_products': total_products,
        'total_invoices': total_invoices,
        # Current month
        'current_month_invoice_count': current_month_invoice_count,
        'current_month_purchases_amount': current_month_purchases_amount,
        'current_month_payments_amount': current_month_payments_amount,
        'current_month_expense_total': abs(current_expense_total),
        'current_month_expense_count': current_expense_count,
        'current_month_purchase_amount': current_month_purchase_amount,
        'current_month_purchase_count': current_month_purchase_count,
        'current_month_payment_percentage': round(current_month_payment_percentage, 1),
        
        # Last month
        'last_month_invoice_count': last_month_invoice_count,
        'last_month_purchases_amount': last_month_purchases_amount,
        'last_month_payments_amount': last_month_payments_amount,
        'last_month_expense_total': abs(last_expense_total),
        'last_month_expense_count': last_expense_count,
        'last_month_payment_percentage': round(last_month_payment_percentage, 1),
        
        # Overall
        'total_invoices': total_invoices,
        'total_purchases': total_purchases,
        'total_payments': total_payments,
        'total_returns': total_returns,
        'total_others': total_others,
        'total_balance': total_balance,
        'total_expenses': abs(total_expenses),
        'total_expense_count': total_expense_count,
        'overall_payment_percentage': round(overall_payment_percentage, 1),
        
        # Inventory
        'total_stock': total_stock,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'discount_products': discount_products,
        
        # Recent activity
        'recent_invoices': recent_invoices,
        'recent_expenses': recent_expenses,

        # Brands
        'users': users,
        'users_filter': users_filter,
    })
    
    return render(request, 'mobile_v1/home.html', context)

def product_inventory_stock_add(request):
    brand = request.GET.get('brand')
    product_id = request.GET.get('product_id')
    if not brand or not product_id:
        return JsonResponse({'status': 'error', 'message': 'Try again later.'})
    try:
        inventory = get_object_or_404(Inventory, product__id=product_id, user__id=brand)
    except Inventory.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Inventory not found.'})
    except Inventory.MultipleObjectsReturned:
        return JsonResponse({'status': 'error', 'message': 'Multiple inventory records found. Please contact support.'})
    if request.method == 'POST':
        added_stock = request.POST.get('added_stock', '0').strip()
        stock_alert = request.POST.get('stock_alert', '0').strip()
        title = request.POST.get('title', '').strip()
        only_alert = request.POST.get('only_alert')
        only_alert = True if only_alert == 'true' else False
        reduce_stock = request.POST.get('reduce_stock')
        reduce_stock = True if reduce_stock == 'true' else False
        description = title if title else 'Admin'
        description += ' via Mobile App'
        try:
            if stock_alert.isdigit():
                inventory.alert_level = int(stock_alert)
            if only_alert:
                inventory.save()
                return JsonResponse({'status': 'success', 'message': 'Alert level updated successfully.'})
            added_stock = int(added_stock)
            if reduce_stock:
                added_stock = -added_stock
            if added_stock == 0:
                return JsonResponse({'status': 'error', 'message': 'Invalid stock quantity.'})
            inventory.current_stock += added_stock
            inventory.save()
            # Log the inventory addition
            log_entry = InventoryLog(
                user = inventory.user,
                product = inventory.product,
                change = added_stock,
                description = description
            )
            log_entry.save()

            return JsonResponse({'status': 'success', 'message': 'Stock added successfully.'})
        except ValueError:
            return JsonResponse({'status': 'error', 'message': 'Invalid stock quantity.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    