"""Authentication for the operator console at /console/.

Deliberately separate from the business login, in both directions:

  * The console identity lives under its own session key and NEVER calls django's
    login(), so request.user is untouched. Signing in at /console/login grants nothing
    in the business app.
  * The console decorator ignores request.user entirely, so a business owner logged in
    normally — even one who somehow learns an admin password — gets nothing here without
    going through /console/login.

PlatformAdmin is a standalone table with its own username and password columns — there is
no auth.User behind it, so the two populations cannot overlap at all. The stored password
is a Django hash (see PlatformAdmin.set_password), so only the table is ours; the hashing
is Django's.

This mirrors the shape already used for the mobile magic-link (mobile_auth.py): a distinct
session/cookie identity resolved by a decorator, not piggybacked on the shared session
user.
"""
from functools import wraps

from django.contrib.auth.hashers import make_password
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import PlatformAdmin

# Its own session key — not "_auth_user_id", so the two identities cannot be confused.
SESSION_KEY = "console_admin_id"


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        # Left-most entry is the original client; the rest are proxies.
        return fwd.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def authenticate_admin(username, password):
    """Return the active PlatformAdmin for these credentials, or None.

    Every failure path returns None the same way, so the caller cannot tell an unknown
    username from a wrong password from a revoked admin.
    """
    admin = PlatformAdmin.objects.filter(username=username).first()
    if admin is None:
        # Hash something anyway so a missing username doesn't return measurably faster
        # than a wrong password.
        make_password(password)
        return None
    if not admin.is_active or not admin.check_password(password):
        return None
    return admin


def start_session(request, admin):
    request.session[SESSION_KEY] = admin.pk
    request.session.cycle_key()          # new session id on privilege change
    PlatformAdmin.objects.filter(pk=admin.pk).update(
        last_login_at=timezone.now(), last_login_ip=client_ip(request))


def end_session(request):
    request.session.pop(SESSION_KEY, None)


def current_admin(request):
    """The signed-in PlatformAdmin, or None. Re-read every request so revoking an admin
    (is_active=False) takes effect immediately instead of at their next login."""
    pk = request.session.get(SESSION_KEY)
    if not pk:
        return None
    admin = PlatformAdmin.objects.filter(pk=pk, is_active=True).first()
    if admin is None:
        # Revoked or deleted mid-session — drop the stale key.
        request.session.pop(SESSION_KEY, None)
    return admin


def console_required(view):
    """Gate a console view. Redirects to the console login, never the business one."""

    @wraps(view)
    def inner(request, *args, **kwargs):
        admin = current_admin(request)
        if admin is None:
            return redirect("%s?next=%s" % (reverse("console_login"), request.path))
        request.platform_admin = admin
        request.platform_admin_upper = str(admin).upper()
        return view(request, *args, **kwargs)

    return inner
