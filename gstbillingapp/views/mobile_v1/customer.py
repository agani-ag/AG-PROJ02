# Django imports
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.contrib.auth.hashers import check_password

# Models
from ...models import (
    Customer, UserProfile, Invoice
)

# Utility functions
from ...utils import parse_code_GS

# ================= Customer =============================
def customer(request):
    context = {}
    cid = request.GET.get('cid', None)
    cid_data = parse_code_GS(cid)
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
    cid = request.GET.get('cid', None)
    cid_data = parse_code_GS(cid)
    customer_id = cid_data.get('C', None)
    user_id = cid_data.get('GS', None)
    try:
        user = get_object_or_404(UserProfile, user__id=user_id)
        context['users'] = user
        customer = get_object_or_404(Customer, user__id=user_id, id=customer_id)
        context['customer'] = customer
    except:
        pass
    invoices = Invoice.objects.filter(user__id=user_id, invoice_customer__id=customer_id)
    context['invoices'] = invoices
    context['invoices_count'] = len(invoices)
    return render(request, 'mobile_v1/customer/invoices.html', context)