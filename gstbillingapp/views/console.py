"""Operator console screens — mounted at /console/ (see gstbillingapp/console_urls.py).

This is the platform side of GSTSync: the screens the people who RUN the product use to
create and manage the businesses that use it. It is not part of the business app and
shares none of its navigation, base template or session identity.

Everything here is gated by @console_required, which reads the console's own session key
and ignores request.user entirely (see console_auth.py).
"""
import datetime

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..console_auth import authenticate_admin, console_required, end_session, start_session
from ..console_ops import (
    business_footprint, business_summary, create_business, looks_like_test_data,
    purge_business, reset_business_password, set_business_active,
)
from ..models import Invoice, PlatformAdmin, UserProfile


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def console_login(request):
    """The console's own login. Never redirects to, or accepts a session from, the
    business login."""
    if request.method == "POST":
        admin = authenticate_admin(request.POST.get("username", "").strip(),
                                   request.POST.get("password", ""))
        if admin is None:
            # One message for every failure — never reveal which part was wrong.
            return render(request, "console/login.html",
                          {"error": "Invalid credentials."}, status=401)
        start_session(request, admin)
        nxt = request.GET.get("next") or ""
        # Only ever follow a next= that stays inside the console.
        return redirect(nxt if nxt.startswith("/console/") else "console_businesses")
    return render(request, "console/login.html", {})


def console_logout(request):
    end_session(request)
    return redirect("console_login")


# --------------------------------------------------------------------------- #
# Businesses
# --------------------------------------------------------------------------- #
@console_required
def businesses(request):
    """Every business on the platform. This is the screen that did not exist — which is
    why 16 test tenants accumulated unnoticed."""
    q = (request.GET.get("q") or "").strip()
    show = request.GET.get("show") or "all"

    # Platform admins are not auth.Users at all, so nothing has to be excluded here —
    # every row in auth_user IS a business.
    users = User.objects.select_related("userprofile").order_by("id")
    if q:
        users = users.filter(username__icontains=q) | users.filter(
            userprofile__business_title__icontains=q)

    rows = [business_summary(u) for u in users.distinct()]
    for r in rows:
        r["is_test"] = looks_like_test_data(r)

    # The stat cards are filter buttons, so they count the whole (searched) set — not the
    # slice currently on screen, which would make the numbers change as you click them.
    counts = {
        "count_all": len(rows),
        "count_real": sum(1 for r in rows if not r["is_test"]),
        "count_test": sum(1 for r in rows if r["is_test"]),
        "count_suspended": sum(1 for r in rows if not r["is_active"]),
    }

    if show == "test":
        rows = [r for r in rows if r["is_test"]]
    elif show == "real":
        rows = [r for r in rows if not r["is_test"]]
    elif show == "suspended":
        rows = [r for r in rows if not r["is_active"]]

    return render(request, "console/businesses.html", dict(counts, **{
        "rows": rows,
        "q": q,
        "show": show,
        "total": len(rows),
        "test_count": sum(1 for r in rows if r["is_test"]),
    }))


@console_required
def business_new(request):
    """Create a business. This replaces the public signup route."""
    if request.method == "POST":
        d = request.POST
        username = (d.get("username") or "").strip()
        password = d.get("password") or ""
        title = (d.get("business_title") or "").strip()

        errors = []
        if not username:
            errors.append("Username is required.")
        elif User.objects.filter(username__iexact=username).exists():
            errors.append("That username is already taken.")
        if not title:
            errors.append("Business name is required.")
        try:
            validate_password(password)
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(request, "console/business_form.html",
                          {"errors": errors, "d": d}, status=400)

        user, _ = create_business(
            username=username, password=password, title=title,
            brand=(d.get("business_brand") or "").strip(),
            gst=(d.get("business_gst") or "").strip(),
            phone=(d.get("business_phone") or "").strip(),
            email=(d.get("business_email") or "").strip(),
            address=(d.get("business_address") or "").strip(),
            created_by=request.platform_admin,
        )
        messages.success(request, "Business '%s' created." % user.username)
        return redirect("console_business_detail", user_id=user.id)

    return render(request, "console/business_form.html", {"d": {}})


@console_required
def business_detail(request, user_id):
    user = get_object_or_404(User.objects.select_related("userprofile"), id=user_id)
    summary = business_summary(user)
    summary["is_test"] = looks_like_test_data(summary)
    return render(request, "console/business_detail.html", {"b": summary})


@console_required
@require_POST
def business_toggle_active(request, user_id):
    user = get_object_or_404(User, id=user_id)
    set_business_active(user, not user.is_active)
    messages.success(request, "'%s' is now %s." % (
        user.username, "active" if user.is_active else "suspended"))
    return redirect("console_business_detail", user_id=user.id)


@console_required
@require_POST
def business_reset_password(request, user_id):
    user = get_object_or_404(User, id=user_id)
    password = request.POST.get("password") or ""
    try:
        validate_password(password, user=user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("console_business_detail", user_id=user.id)
    reset_business_password(user, password)
    messages.success(request, "Password reset for '%s'." % user.username)
    return redirect("console_business_detail", user_id=user.id)


@console_required
def business_purge(request, user_id):
    """Delete a business and everything it owns. Irreversible, so it is a two-step flow:
    a preview of every row that would go, then a confirmation that requires typing the
    username exactly."""
    user = get_object_or_404(User.objects.select_related("userprofile"), id=user_id)
    footprint = business_footprint(user)

    if request.method == "POST":
        typed = (request.POST.get("confirm_username") or "").strip()
        if typed != user.username:
            return render(request, "console/business_purge.html", {
                "b": business_summary(user), "footprint": footprint,
                "total": sum(footprint.values()),
                "error": "Type the username exactly to confirm.",
            }, status=400)
        name = user.username
        removed = purge_business(user)
        messages.success(request, "Purged '%s' — %d rows deleted." % (name, removed["total"]))
        return redirect("console_businesses")

    return render(request, "console/business_purge.html", {
        "b": business_summary(user),
        "footprint": footprint,
        "total": sum(footprint.values()),
    })


# --------------------------------------------------------------------------- #
# Admins
# --------------------------------------------------------------------------- #
@console_required
def admins(request):
    return render(request, "console/admins.html", {
        "admins": PlatformAdmin.objects.all(),
        "me": request.platform_admin,
    })


@console_required
def change_password(request):
    """An admin changes their OWN password. Never anyone else's — a second admin's
    password is reset from the server, the same place console access is granted."""
    me = request.platform_admin
    if request.method == "POST":
        current = request.POST.get("current_password") or ""
        new = request.POST.get("new_password") or ""
        confirm = request.POST.get("confirm_password") or ""

        errors = []
        if not me.check_password(current):
            errors.append("Current password is incorrect.")
        if new != confirm:
            errors.append("The new passwords do not match.")
        try:
            validate_password(new)
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(request, "console/change_password.html",
                          {"errors": errors}, status=400)

        me.set_password(new)
        me.save(update_fields=["password"])
        messages.success(request, "Your console password has been changed.")
        return redirect("console_admins")

    return render(request, "console/change_password.html", {})
