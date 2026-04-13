# Django imports
from gstbilling import settings
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
# Models
from ..models import Book, Customer, UserProfile

# Utility functions
from ..utils import (
    add_customer_book, add_customer_userid
)

# Forms
from ..forms import CustomerForm

# Python imports
import json

# Variables
CPASSWORD = 'pass123'

# ================= Customer Views ===========================
@login_required
def customers(request):
    context = {}
    context['customers'] = Customer.objects.filter(user=request.user).order_by('customer_name')
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
            # new_customer.customer_password = make_password(CPASSWORD)
            new_customer.customer_password = CPASSWORD
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
    if not customer_obj.customer_password:
        # customer_obj.customer_password = make_password(CPASSWORD)
        customer_obj.customer_password = CPASSWORD
        customer_obj.save()
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
    context['customer_password'] = customer_obj.customer_password
    print("customer_password:", customer_obj.customer_password)
    context['default_password'] = CPASSWORD
    print("default_password:", CPASSWORD)
    print(context['customer_password'] == context['default_password'])
    context['id'] = customer_obj.id
    return render(request, 'customers/customer_edit.html', context)


@login_required
def customer_delete(request):
    if request.method == "POST":
        customer_id = request.POST["customer_id"]
        customer_obj = get_object_or_404(Customer, user=request.user, id=customer_id)
        customer_obj.delete()
    return redirect('customers')


@login_required
def customers_collection_calendar(request):
    context = {}
    case_mapping = dict(Customer.DAYS)
    filter_day = request.GET.get('filter')
    queryset = Book.objects.filter(user=request.user).exclude(customer_id__isnull=True).order_by('customer__customer_name')
    if filter_day:
        queryset = queryset.filter(customer__collection_day=filter_day)
        context['filter_day_display'] = case_mapping.get(int(filter_day))
    context['books'] = queryset
    return render(request, 'customers/collection_calendar.html', context)


# ================= Customer API Views ===========================
@login_required
def customersjson(request):
    customers = list(Customer.objects.filter(user=request.user).values())
    return JsonResponse(customers, safe=False)


@csrf_exempt
def customer_default_password(request):
    if request.method == "POST":
        customer_userid = request.POST["customer_userid"]
        customer_obj = get_object_or_404(Customer, customer_userid=customer_userid)
        # customer_obj.customer_password = make_password(CPASSWORD)
        customer_obj.customer_password = CPASSWORD
        customer_obj.save()
        return JsonResponse({'status': 'success', 'message': f"{customer_userid.upper()} customer's password reset to default."})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to reset customer password.'})


@csrf_exempt
def customerall_userid_set(request):
    if request.method == "POST":
        customer_user = request.POST["customer_userid"]
        customer_count = list(Customer.objects.filter(user_id=customer_user))
        customer_obj = Customer.objects.filter(user_id=customer_user)
        for customer in customer_obj:
            if not customer.customer_password:
                # customer.customer_password = make_password(CPASSWORD)
                customer.customer_password = CPASSWORD
            customer.is_mobile_user = True
            customer.save()
            add_customer_userid(customer)
        return JsonResponse({'status': 'success', 'message': f'{len(customer_count)} Customer User IDs set successfully.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to set customer user IDs.'})


@csrf_exempt
def customer_is_mobile_user(request):
    if request.method == "POST":
        customer_userid = request.POST.get("customer_userid", None)
        if not customer_userid:
            return JsonResponse({'status': 'error', 'message': 'Customer UserID is required.'})
        try:
            customer_obj = Customer.objects.get(customer_userid=customer_userid)
            if customer_obj.is_mobile_user:
                is_mobile_user = False
                message = f'Customer {customer_userid.upper()} mobile login is turned off.'
            else:
                is_mobile_user = True
                message = f'Customer {customer_userid.upper()} mobile login is turned on.'
            customer_obj.is_mobile_user = is_mobile_user
            customer_obj.save()
            return JsonResponse({'status': 'success', 'message': message})
        except Customer.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Customer not found.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to check mobile user status.'})

@csrf_exempt
def customer_collection_day_update(request):
    if request.method == "POST":
        customer_id = request.POST.get("customer_id", None)
        place = request.POST.get("customer_place", None)
        day = request.POST.get("collection_day", 0)
        if not customer_id:
            return JsonResponse({'status': 'error', 'message': 'Customer ID is required.'})
        try:
            customer_obj = Customer.objects.get(id=customer_id)
            if customer_obj:
                customer_obj.collection_day = day
                customer_obj.customer_place = place
                customer_obj.save()
                message = f'Customer collection day & place updated.'
            return JsonResponse({'status': 'success', 'message': message})
        except Customer.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Customer not found.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to update customer collection day.'})

def show_customer_collection_api(request):
    markdown = request.GET.get('markdown', 'false').lower() == 'true'
    user_id = request.GET.get('user_id', None)
    today = timezone.localdate().weekday()
    collection_day = (today + 1) % 7
    collection_day_name = Customer.DAYS[collection_day][1]
    books = Book.objects.filter(user_id=user_id, customer__collection_day=collection_day)\
        .exclude(customer_id__isnull=True)\
        .order_by('current_balance')

    data = []
    markdown_blocks = []
    markdown_blocks.append(f"*COLLECTION ROUTE* - *{collection_day_name}*")
    for book in books:
        customer = book.customer
        current_balance = round(book.current_balance if book.current_balance else 0, 2)
        data.append({
            'current_balance': current_balance,
            'customer_name': customer.customer_name,
            'customer_place': customer.customer_place,
            'collection_day': customer.collection_day,
        })
        markdown_blocks.append('▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬')
        markdown_blocks.append(f"*{customer.customer_name}*")
        if customer.customer_place:
            markdown_blocks.append(f"Place: {customer.customer_place}")
        markdown_blocks.append(f"Current Balance: ₹{current_balance}")
    # ── Footer ──
    markdown_blocks.append('▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬')
    markdown_blocks.append(f'🦀  Crab AI')
    markdown_formatted = '\n'.join(markdown_blocks)
    if markdown:
        return JsonResponse({'markdown': markdown_formatted}, safe=False)
    return JsonResponse(data, safe=False)

@csrf_exempt
def customer_api_add(request):
    if request.method == "POST":
        business_uid = request.GET.get('business_uid', None)
        if not business_uid:
            return JsonResponse({'status': 'error', 'message': 'Business UID is required.'})
        user_profile = get_object_or_404(UserProfile, business_uid=business_uid)
        if user_profile:
            user = user_profile.user
        data = request.body.decode('utf-8')
        data = json.loads(data)
        inserted_count = 0
        not_inserted_count = 0
        for item in data:
            if item.get('customer_name') == "" and item.get('customer_phone') == "":
                not_inserted_count += 1
            elif Customer.objects.filter(user=user, customer_phone=item.get('customer_phone')).exists():
                not_inserted_count += 1
            else:
                customer = Customer(
                    user=user,
                    customer_name=item.get('customer_name'),
                    customer_phone=item.get('customer_phone'),
                    customer_email=item.get('customer_email', None),
                    customer_address=item.get('customer_address', None),
                    customer_gst=item.get('customer_gst', None),
                    # customer_password=make_password(CPASSWORD),
                    customer_password=CPASSWORD,
                    is_mobile_user=True
                )
                customer.save()
                # create customer book & userid
                add_customer_book(customer)
                add_customer_userid(customer)
                inserted_count += 1
        return JsonResponse({'status': 'success', 'message': f'{inserted_count} Customers added successfully. {not_inserted_count} Customers not added.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add customers.'})