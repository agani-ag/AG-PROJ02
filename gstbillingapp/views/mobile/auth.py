# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password, check_password

# Models
from ...models import Customer


# ================= User Management =============================
def login_view(request):
    context = {}
    if request.method == "POST":
        customer_userid = request.POST.get("customer_userid")
        customer_password = request.POST.get("customer_password")
        context["customer_userid"] = customer_userid
        try:
            customer = Customer.objects.get(customer_userid=customer_userid, is_mobile_user=True)
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