# Django imports
from django.http import JsonResponse
from django.db.models import Q, CharField
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, render

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