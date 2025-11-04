# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.contrib.auth.hashers import check_password

# Models
from ...models import Customer

# Python imports
import re

# ================= User Management =============================
def login_view(request):
    context = {}
    customer_userid = request.GET.get("customer_userid", "")
    context["customer_userid"] = customer_userid
    if request.method == "POST":
        customer_userid = request.POST.get("customer_userid")
        customer_password = request.POST.get("customer_password")
        context["customer_userid"] = customer_userid
        user_type = pick_middle_letters(customer_userid.lower())
        try:
            if user_type == "c":
                customer = Customer.objects.get(customer_userid=customer_userid.lower(), is_mobile_user=True)
                if not check_password(customer_password, customer.customer_password):
                    context["error_message"] = "Valid User & Invalid password."
                    return render(request, 'mobile/auth/login.html', context)
        except Customer.DoesNotExist:
            context["error_message"] = "Invalid username or password."
            return render(request, 'mobile/auth/login.html', context)

        user = customer.user
        if user:
            # Manually set the backend, because multiple are configured
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            # Authenticate the user
            login(request, user)
            session = request.session
            session['customer_id'] = customer.id
            return redirect("invoice_create")
        else:
            context["error_message"] = "Invalid username or password."
    return render(request, 'mobile/auth/login.html', context)


def logout_view(request):
    logout(request)
    del request.session['customer_id']
    return redirect('login_view')


def find_user_view(request):
    context = {}
    if request.method == "POST":
        customer_input_email = request.POST.get("customer_input_email", "")
        customer_input_phone = request.POST.get("customer_input_phone", "")
        customer_input_gst = request.POST.get("customer_input_gst", "")
        try:
            if customer_input_email:
                customer = Customer.objects.filter(customer_email=customer_input_email, is_mobile_user=True)
                context["customer"] = customer
                context["customer_input"] = "Email"
                context["customer_result"] = True
            if customer_input_phone:
                customer = Customer.objects.filter(customer_phone=customer_input_phone, is_mobile_user=True)
                context["customer"] = customer
                context["customer_input"] = "Phone"
                context["customer_result"] = True
            if customer_input_gst:
                customer = Customer.objects.filter(customer_gst=customer_input_gst, is_mobile_user=True)
                context["customer"] = customer
                context["customer_input"] = "GST Number"
                context["customer_result"] = True
            return render(request, 'mobile/auth/find_user.html',context)
        except Customer.DoesNotExist:
            return render(request, 'mobile/auth/find_user.html',context)
    return render(request, 'mobile/auth/find_user.html',context)


def forgot_password_view(request):
    context = {}
    context["customer_userid"] = request.GET.get("customer_userid", "")
    if request.method == "POST":
        customer_userid = request.POST.get("customer_userid")
        new_password = request.POST.get("new_password")
        pass
    return render(request, 'mobile/auth/forget_password.html',context)


# ================= Auth Utils =========================

def pick_middle_letters(s):
    # Find all positions of digits
    digit_positions = [m.start() for m in re.finditer(r'\d', s)]
    
    if len(digit_positions) < 2:
        return ""  # Not enough numbers to define a middle section

    # Define the range between the first and last digit
    start = digit_positions[0]
    end = digit_positions[-1]

    # Extract substring between those digits
    middle_section = s[start+1:end]

    # Keep only letters
    letters = re.findall(r'[A-Za-z]+', middle_section)
    return ''.join(letters)