# Django imports
from django.forms import FloatField
from django.utils import timezone
from django.http import JsonResponse
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, render
from django.db.models import (
    Sum, Case, When, FloatField, F,Q, CharField, Min, Max
)
# Models
from ...models import (
    Customer, UserProfile, Invoice,
    BookLog
)

# Utility functions
from ...utils import parse_code_GS

# ================= Customer =============================
def customer(request):
    context = {}
    cid = request.GET.get('cid', None)
    if not cid:
        return render(request, 'mobile_v1/customer/customer.html', {
            'error': 'Invalid customer link'
        })
    cid_data = parse_code_GS(cid)
    if not cid_data:
        return render(request, 'mobile_v1/customer/customer.html', {
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
    return render(request, 'mobile_v1/customer/customer.html', context)

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
    )
    # Fill in context with totals, using 0 if None
    total_purchased = totals['total_purchased'] or 0
    total_paid = totals['total_paid'] or 0
    total_returned = totals['total_returned'] or 0
    total_others = totals['total_others'] or 0
    total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
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
    )
    current_month_total_purchased = current_month_totals['current_month_total_purchased'] or 0
    current_month_total_paid = current_month_totals['current_month_total_paid'] or 0
    context['current_month_total_purchased'] = abs(int(current_month_total_purchased))
    context['current_month_total_paid'] = abs(int(current_month_total_paid))
    
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
    )
    last_month_total_purchased = last_month_totals['last_month_total_purchased'] or 0
    last_month_total_paid = last_month_totals['last_month_total_paid'] or 0
    context['last_month_total_purchased'] = abs(int(last_month_total_purchased))
    context['last_month_total_paid'] = abs(int(last_month_total_paid))
    return render(request, 'mobile_v1/customer/home.html', context)