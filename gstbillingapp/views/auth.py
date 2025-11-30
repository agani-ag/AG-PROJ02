# Django imports
from django.contrib.auth import login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

# Project imports
from gstbilling import settings

# Forms
from ..forms import UserProfileForm


# ================= User Management =============================
def login_view(request):
    if request.user.is_authenticated:
        return redirect("invoice_create")
    context = {}
    if request.GET.get("admin"):
        context["admin"] = True
    context["admin_password"] = settings.PRODUCT
    auth_form = AuthenticationForm(request)
    if request.method == "POST":
        auth_form = AuthenticationForm(request, data=request.POST)
        if auth_form.is_valid():
            user = auth_form.get_user()
            if user:
                login(request, user)
                return redirect("invoice_create")
        else:
            context["error_message"] = auth_form.get_invalid_login_error()
    context["auth_form"] = auth_form
    return render(request, 'auth/login.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("invoice_create")
    context = {}
    signup_form = UserCreationForm()
    profile_edit_form = UserProfileForm()
    context["signup_form"] = signup_form
    context["profile_edit_form"] = profile_edit_form

    
    if request.method == "POST":
        signup_form = UserCreationForm(request.POST)
        profile_edit_form = UserProfileForm(request.POST)
        context["signup_form"] = signup_form
        context["profile_edit_form"] = profile_edit_form

        if signup_form.is_valid():
            user = signup_form.save()
        else:
            context["error_message"] = signup_form.errors
            return render(request, 'auth/signup.html', context)
        if profile_edit_form.is_valid():
            userprofile = profile_edit_form.save(commit=False)
            userprofile.user = user
            userprofile.business_uid = f"{settings.PRODUCT_PREFIX}{user.id}"
            userprofile.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect("invoice_create")

    return render(request, 'auth/signup.html', context)

def logout_view(request):
    logout(request)
    return redirect('login_view')

# ================= Auth API Views ===========================
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from ..models import UserProfile
import json
@csrf_exempt
def passkey_auth(request):
    # Only allow POST requests
    if request.method == "POST":
        try:
            # Parse the incoming JSON body
            data = json.loads(request.body)
            passkey = data.get("passkey")

            # Define valid passkeys
            passkeys = {
                "66666": 1,
                "77777": 2,
                "88888": 3
            }

            # Check if the passkey is valid
            user_id = passkeys.get(passkey)

            if not user_id:
                return JsonResponse({"error": "Invalid passkey"}, status=400)

            # Look up the user profile using the user_id
            user_profile = get_object_or_404(UserProfile, user__id=user_id)

            # Log the user in
            login(request, user_profile.user, backend='django.contrib.auth.backends.ModelBackend')

            # Return a successful response
            return JsonResponse({"message": "Passkey authentication successful"}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)