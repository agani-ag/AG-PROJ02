# Django imports
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.hashers import make_password, check_password

# Models
from ..models import Customer

# Utility functions
from ..utils import (
    add_customer_book, add_customer_userid
)

# Forms
from ..forms import CustomerForm

# Variables
CPASSWORD = 'password123'

# ================= Customer Views ===========================
@login_required
def customers(request):
    context = {}
    context['customers'] = Customer.objects.filter(user=request.user)
    return render(request, 'customers/customers.html', context)


@login_required
def customer_add(request):
    if request.method == "POST":
        customer_form = CustomerForm(request.POST)
        new_customer = customer_form.save(commit=False)
        new_customer.user = request.user
        new_customer.customer_password = make_password(CPASSWORD)
        new_customer.is_mobile_user = request.POST.get('is_mobile_user') == 'on'
        new_customer.save()
        # create customer book & userid
        add_customer_book(new_customer)
        add_customer_userid(new_customer)
        return redirect('customers')
    context = {}
    context['customer_form'] = CustomerForm()
    context['is_mobile_user'] = False
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_edit(request, customer_id):
    customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
    if request.method == "POST":
        customer_form = CustomerForm(request.POST, instance=customer_obj)
        if customer_form.is_valid():
            new_customer = customer_form.save(commit=False)
            new_customer.is_mobile_user = request.POST.get('is_mobile_user') == 'on'
            new_customer.save()
            return redirect('customers')
    context = {}
    context['customer_id'] = customer_id
    context['customer_form'] = CustomerForm(instance=customer_obj)
    context['is_mobile_user'] = customer_obj.is_mobile_user
    context['customer_userid'] = customer_obj.customer_userid
    if check_password(CPASSWORD, customer_obj.customer_password):
        customer_password = [True,'Unchanged','red']
    else:
        customer_password = [True,'Changed','green']
    context['customer_password'] = customer_password
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_delete(request):
    if request.method == "POST":
        customer_id = request.POST["customer_id"]
        customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
        customer_obj.delete()
    return redirect('customers')


@login_required
def customer_default_password(request):
    if request.method == "POST":
        customer_id = request.POST["customer_id"]
        customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
        customer_obj.customer_password = make_password(CPASSWORD)
        customer_obj.save()
        return redirect('customer_edit', customer_id=customer_id)


# ================= Customer API Views ===========================
@login_required
def customersjson(request):
    customers = list(Customer.objects.filter(user=request.user).values())
    return JsonResponse(customers, safe=False)