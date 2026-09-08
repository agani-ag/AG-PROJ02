# Django imports
from django.contrib.auth import login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import AuthenticationForm
from django.utils.http import url_has_allowed_host_and_scheme


def _safe_next(request):
    """The ?next=/... target if it's a safe same-site path, else None."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return None


# ================= User Management =============================
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "landing_page")
    context = {}
    context["next"] = request.GET.get("next") or request.POST.get("next") or ""
    auth_form = AuthenticationForm(request)
    if request.method == "POST":
        auth_form = AuthenticationForm(request, data=request.POST)
        if auth_form.is_valid():
            user = auth_form.get_user()
            if user:
                login(request, user)
                # "Remember me": keep the session for its full cookie age (Django default
                # 2 weeks) so it survives closing the browser. Unchecked → a session cookie
                # that the browser drops on close, so a shared/public machine is signed out.
                if request.POST.get("remember"):
                    request.session.set_expiry(None)  # use SESSION_COOKIE_AGE
                else:
                    request.session.set_expiry(0)     # expire at browser close
                # Honour ?next=/... so a deep link resumes where the user was headed.
                return redirect(_safe_next(request) or "landing_page")
        else:
            context["error_message"] = auth_form.get_invalid_login_error()
    context["auth_form"] = auth_form
    return render(request, 'auth/login.html', context)


# Self-service signup was removed entirely. A business is created by an operator at
# /console/business/new, which builds the User and its UserProfile in one transaction.
# The public route let anyone who found the URL mint a tenant (16 test tenants
# accumulated that way), and it could half-succeed — leaving a login with no business
# profile, which breaks every business screen.


def logout_view(request):
    # Mark this device offline immediately (so the live count drops) but KEEP the row as
    # device history — the same browser is recognised again on its next login.
    token = request.session.get("device_token")
    if request.user.is_authenticated and token:
        from datetime import timedelta
        from django.utils import timezone
        from ..models import ActiveDevice
        from .presence import PRESENCE_WINDOW
        stamp = timezone.now() - PRESENCE_WINDOW - timedelta(seconds=1)
        # .update() bypasses auto_now so the backdated (offline) stamp sticks.
        ActiveDevice.objects.filter(user=request.user, token=token).update(last_seen=stamp)
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
                "11111": 1,
                "22222": 2,
                "33333": 3,
                "44444": 4,
                "55555": 5,
                "97911": 1,
            }

            # Check if the passkey is valid
            user_id = passkeys.get(passkey)

            if not user_id:
                return JsonResponse({"error": "User not found"}, status=400)

            # Look up the user profile using the user_id
            user_profile = get_object_or_404(UserProfile, user__id=user_id)

            if not user_profile.user.is_active:
                return JsonResponse({"error": "User account is inactive"}, status=403)

            # Log the user in
            login(request, user_profile.user, backend='django.contrib.auth.backends.ModelBackend')

            # Return a successful response
            return JsonResponse({"message": "Passkey authentication successful"}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)