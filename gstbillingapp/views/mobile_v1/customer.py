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
    BookLog
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
        is_active=True
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
    context = {}
    users = UserProfile.objects.filter()
    context['users'] = users
    customers = Customer.objects.filter().order_by('customer_name')
    context['customers'] = customers
    return render(request, 'mobile_v1/static.html', context)