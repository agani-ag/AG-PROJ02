# Django imports
from django.forms import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.hashers import make_password, check_password

# Models
from ..models import Customer

# Utility functions
from ..utils import (
    add_customer_book, add_customer_userid,
    customer_already_exists
)

# Forms
from ..forms import CustomerForm

# Python imports
import json

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
    context = {}
    if request.method == "POST":
        customer_form = CustomerForm(request.POST)
        if request.POST.get('customer_phone') == "":
            context["error_message"] = "Customer phone is required."
        elif Customer.objects.filter(user=request.user, customer_phone=request.POST.get('customer_phone')).exists():
            context["error_message"] = "Customer with this phone number already exists."
        else:
            new_customer = customer_form.save(commit=False)
            new_customer.user = request.user
            new_customer.customer_password = make_password(CPASSWORD)
            new_customer.is_mobile_user = request.POST.get('is_mobile_user') == 'on'
            new_customer.save()
            # create customer book & userid
            add_customer_book(new_customer)
            add_customer_userid(new_customer)
            return redirect('customers')
        context['customer_form'] = customer_form
        return render(request, 'customers/customer_edit.html', context)
    context['customer_form'] = CustomerForm()
    context['is_mobile_user'] = False
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_edit(request, customer_id):
    customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
    if request.method == "POST":
        context = {}
        customer_form = CustomerForm(request.POST, instance=customer_obj)
        if request.POST.get('customer_phone') == "":
            context["error_message"] = "Customer phone is required."
        elif Customer.objects.filter(user=request.user,
                customer_phone=request.POST.get('customer_phone')).exclude(id=customer_id).exists():
            context["error_message"] = "Customer with this phone number already exists."
        elif customer_form.is_valid():
            new_customer = customer_form.save(commit=False)
            new_customer.is_mobile_user = request.POST.get('is_mobile_user') == 'on'
            new_customer.save()
            return redirect('customers')
        context['customer_form'] = customer_form
        return render(request, 'customers/customer_edit.html', context)
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


@login_required
def customerall_userid_set(request):
    customer_obj = Customer.objects.filter(user=request.user)
    for customer in customer_obj:
        add_customer_userid(customer)
        customer.is_mobile_user = True
        customer.save()
    return redirect('customers')


# ================= Customer API Views ===========================
@login_required
def customersjson(request):
    customers = list(Customer.objects.filter(user=request.user).values())
    return JsonResponse(customers, safe=False)


@csrf_exempt
def customer_api_add(request, user):
    if request.method == "POST":
        data = request.body.decode('utf-8')
        data = json.loads(data)
        inserted_count = 0
        not_inserted_count = 0
        for item in data:
            if customer_already_exists(user, item.get('customer_phone'),
                    item.get('customer_email'), item.get('customer_gst')):
                not_inserted_count += 1
                continue
            if 'customer_name' not in item:
                not_inserted_count += 1
                continue
            customer = Customer(
                user_id=user,
                customer_name=item.get('customer_name'),
                customer_email=item.get('customer_email', None),
                customer_phone=item.get('customer_phone', None),
                customer_address=item.get('customer_address', None),
                customer_gst=item.get('customer_gst', None),
                customer_password=make_password(CPASSWORD),
                is_mobile_user=True
            )
            customer.save()
            # create customer book & userid
            add_customer_book(customer)
            add_customer_userid(customer)
            inserted_count += 1
        return JsonResponse({'status': 'success', 'message': f'{inserted_count} Customers added successfully. {not_inserted_count} Customers not added.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add customers.'})