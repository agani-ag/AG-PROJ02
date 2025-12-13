# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.decorators import login_required
from django.utils import timezone

# Models
from ...models import Customer, UserProfile, Employee, User

# Python imports
import re

# ================= Login Selection =============================
def login_selection(request):
    """Main login selection screen for mobile"""
    return render(request, 'mobile/auth/login_selection.html')


# ================= Owner Login =============================
def owner_login_view(request):
    """Login for business owner"""
    context = {}
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        
        try:
            user = User.objects.get(username=username)
            if user.check_password(password):
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                request.session['user_type'] = 'owner'
                return redirect("mobile_owner_dashboard")
            else:
                context["error_message"] = "Invalid password."
        except User.DoesNotExist:
            context["error_message"] = "Invalid username."
    
    return render(request, 'mobile/auth/owner_login.html', context)


# ================= Employee Login =============================
def employee_login_view(request):
    """Login for employees"""
    context = {}
    if request.method == "POST":
        employee_userid = request.POST.get("employee_userid")
        employee_password = request.POST.get("employee_password")
        
        try:
            employee = Employee.objects.get(employee_userid=employee_userid.lower(), is_active=True)
            if check_password(employee_password, employee.employee_password):
                # Log in as the business owner (employee.user_profile.user)
                user = employee.user_profile.user
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                
                # Store employee info in session
                request.session['user_type'] = 'employee'
                request.session['employee_id'] = employee.id
                request.session['employee_name'] = employee.employee_name
                request.session['employee_role'] = employee.role
                
                # Update last login
                employee.last_login = timezone.now()
                employee.save()
                
                return redirect("mobile_employee_dashboard")
            else:
                context["error_message"] = "Invalid password."
        except Employee.DoesNotExist:
            context["error_message"] = "Invalid employee ID."
    
    return render(request, 'mobile/auth/employee_login.html', context)


# ================= Customer Login =============================
def customer_login_view(request):
    """Login for customers"""
    context = {}
    customer_userid = request.GET.get("customer_userid", "")
    context["customer_userid"] = customer_userid
    
    if request.method == "POST":
        customer_userid = request.POST.get("customer_userid")
        customer_password = request.POST.get("customer_password")
        context["customer_userid"] = customer_userid
        
        try:
            customer = Customer.objects.get(customer_userid=customer_userid.lower(), is_mobile_user=True)
            if check_password(customer_password, customer.customer_password):
                user = customer.user
                if user:
                    user.backend = 'django.contrib.auth.backends.ModelBackend'
                    login(request, user)
                    request.session['user_type'] = 'customer'
                    request.session['customer_id'] = customer.id
                    request.session['customer_name'] = customer.customer_name
                    return redirect("mobile_customer_dashboard")
                else:
                    context["error_message"] = "Account not properly configured."
            else:
                context["error_message"] = "Invalid password."
        except Customer.DoesNotExist:
            context["error_message"] = "Invalid username or password."
    
    return render(request, 'mobile/auth/customer_login.html', context)


# ================= User Management (Legacy - keeping for compatibility) =============================
def login_view(request):
    """Legacy login view - redirects to selection"""
    return redirect('mobile_login_selection')


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