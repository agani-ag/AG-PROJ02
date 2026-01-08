# Django imports
from django.forms import FloatField
from django.utils import timezone
from django.http import JsonResponse
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, render
from django.db.models import (
    Sum, Case, When, FloatField, IntegerField,
    F,Q, CharField, Min, Max, Count
)

# Models
from ...models import (
    Customer, UserProfile, Invoice,
    BookLog, ExpenseTracker
)

# Python imports
import json
import num2words

# Utility functions
from ...utils import parse_code_GS

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
    total_balance = abs(total_purchased) - abs(total_paid)
    # total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
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
    
    # Base querysets
    users = UserProfile.objects.all().order_by('business_title')
    customers_qs = Customer.objects.select_related('user').order_by('customer_name')
    
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
    
    # Base querysets
    users = UserProfile.objects.all().order_by('business_title')
    customers = Customer.objects.all().order_by('customer_name')
    invoices_qs = Invoice.objects.select_related('user', 'invoice_customer').order_by('-invoice_date', '-invoice_number')
    
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
        })
    
    return render(request, 'mobile_v1/invoices.html', context)


def books(request):
    """Books listing with filtering, search, and pagination"""
    context = {}
    
    # Get filter parameters
    user_id = request.GET.get('user_id', '')
    customer_id = request.GET.get('customer_id', '')
    search_query = request.GET.get('search', '').strip()
    filter_type = request.GET.get('filter_type', 'all')  # all, payments, purchases, returns, others
    status_filter = request.GET.get('status_filter', 'active')  # active, inactive, all
    page_number = request.GET.get('page', 1)
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user')
    
    # Base queryset
    books_qs = BookLog.objects.select_related(
        'parent_book__customer',
        'parent_book__user'
    )
    
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
    total_balance = total_purchased - total_paid
    
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
        'total_purchased': total_purchased,
        'total_paid': total_paid,
        'total_balance': total_balance,
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
            'total_balance': total_balance,
        })
    
    return render(request, 'mobile_v1/books.html', context)

def customersapi(request):
    customers = Customer.objects.all().values(
        business_name=F('customer_name'),
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
        link = f"/mobile/v1/customer/home?cid={userid}"

        if gst not in gst_map:
            gst_map[gst] = []

        if link not in gst_map[gst]:
            gst_map[gst].append(link)

    # Build final response
    customers_dict = {}

    for customer in customers:
        name = customer['name']
        gst = customer['gst']

        customers_dict[name] = {
            'business_name': customer['business_name'],
            'name': name,
            'password': customer['password'],
            'deflink': f"/mobile/v1/customer/home?cid={name}",
            'linklist': gst_map.get(gst, [])
        }

    return JsonResponse(customers_dict, safe=False)

def ExpensesTracker(request):
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
    
    # Get all users for dropdown
    users = UserProfile.objects.all().select_related('user').order_by('business_title')
    
    # Base queryset
    expenses_qs = ExpenseTracker.objects.select_related('user').order_by('-date')
    
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
        })
    
    return render(request, 'mobile_v1/expenses_tracker.html', context)