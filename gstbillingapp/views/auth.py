# Django imports
from django.contrib.auth import login, logout
from django.shortcuts import render, redirect
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

# ================= Passkey sign-in ===========================
import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import passkeys
from ..models import BusinessPasskey


@require_POST
def passkey_auth(request):
    """Sign in with a business's passkey — the 5-character shortcut behind "Sign in with
    passkey" (login page) and "Switch User" (navbar). Passkeys are set per business on the
    console and stored only as a keyed digest (passkeys.py); nothing is hard-coded here.

    CSRF is enforced (both pop-ups send the token), wrong tries are limited per device, and
    every failure gets the same answer, so nothing about the businesses leaks."""
    if passkeys.too_many_tries(request):
        return JsonResponse({"error": "Too many tries — wait a few minutes and try again."},
                            status=429)
    try:
        passkey = json.loads(request.body or b"{}").get("passkey")
    except (ValueError, AttributeError):
        passkey = None
    record = passkeys.authenticate(passkey)
    if record is None:
        passkeys.record_failure(request)
        return JsonResponse({"error": "That passkey isn't right."}, status=400)
    passkeys.clear_failures(request)
    login(request, record.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(0)       # like a password sign-in without "Remember me"
    BusinessPasskey.objects.filter(pk=record.pk).update(last_used_at=timezone.now())
    return JsonResponse({"message": "Signed in."})