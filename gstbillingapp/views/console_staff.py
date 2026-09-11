"""Console: employees across every business, and their SyncUp app logins.

Businesses add, share and switch off their own staff; the console only issues, resets and
deactivates each person's app login (rules in staff.py). One login per person covers every
business they're posted to.
"""
from django.contrib import messages
from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .. import staff
from ..console_auth import console_required
from ..models import Employee, EmployeePosting, StaffLogin, SyncUpSettings
from ..parties import LoginBlocked
from ..syncup_client import SyncUpError, link_base


def _brand(user):
    p = getattr(user, "userprofile", None)
    return ((p.business_brand or p.business_title) if p else None) or user.username


def _back(emp):
    return redirect("console_employee", employee_id=emp.id)


@console_required
def employees(request):
    q = (request.GET.get("q") or "").strip()
    show = request.GET.get("show") or "all"
    if show not in ("all", "login", "nologin", "inactive"):
        show = "all"

    qs = (Employee.objects.select_related("business", "business__userprofile")
          .prefetch_related(Prefetch(
              "postings", queryset=EmployeePosting.objects.filter(is_active=True)
              .select_related("business", "business__userprofile"))))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    logins = {sl.employee_id: sl for sl in StaffLogin.objects.all()}
    domain = SyncUpSettings.load().login_domain

    rows = []
    for e in qs:
        login = logins.get(e.id) or StaffLogin(employee=e)
        rows.append({"e": e, "home": _brand(e.business), "login": login,
                     "email": login.login_email_at(domain),
                     "brands": [_brand(p.business) for p in e.postings.all()],
                     # Can a login be issued now (for the bulk Issue logins)?
                     "ready": (login.login_status != StaffLogin.LOGIN_ACTIVE
                               and not staff.login_blockers(e))})

    # The stat cards are filter buttons, so they count the whole (searched) set.
    ctx = {
        "q": q, "show": show,
        "count_all": len(rows),
        "count_login": sum(1 for r in rows if r["login"].login_status == StaffLogin.LOGIN_ACTIVE),
        "count_none": sum(1 for r in rows if not r["login"].has_login),
        "count_inactive": sum(1 for r in rows if not r["e"].is_active),
    }
    if show == "login":
        rows = [r for r in rows if r["login"].login_status == StaffLogin.LOGIN_ACTIVE]
    elif show == "nologin":
        rows = [r for r in rows if not r["login"].has_login]
    elif show == "inactive":
        rows = [r for r in rows if not r["e"].is_active]
    ctx["rows"] = rows
    ctx["ready_count"] = sum(1 for r in rows if r["ready"])
    return render(request, "console/employees.html", ctx)


@never_cache
@console_required
@require_POST
def employee_login_issue_json(request, employee_id):
    """Issue one employee login for the bulk page (see console_bulk). The password exists
    only in that page. An active login is refused, so bulk never resets a password."""
    emp = get_object_or_404(Employee, id=employee_id)
    if staff.login_of(emp).login_status == StaffLogin.LOGIN_ACTIVE:
        return JsonResponse({"ok": False, "error": "Already has an active login — reset it from "
                                                   "their own page if the password is lost."})
    try:
        password = staff.issue_login(emp)
    except LoginBlocked as e:
        return JsonResponse({"ok": False, "error": " ".join(e.reasons)})
    except SyncUpError as e:
        return JsonResponse({"ok": False, "error": str(e)})
    return JsonResponse({"ok": True, "email": staff.login_of(emp).login_email,
                         "password": password, "phone": emp.phone or ""})


@console_required
def employee_detail(request, employee_id):
    emp = get_object_or_404(Employee.objects.select_related("business", "business__userprofile"),
                            id=employee_id)
    cfg = SyncUpSettings.load()
    postings = emp.postings.select_related("business", "business__userprofile")
    return render(request, "console/employee_detail.html", {
        "emp": emp,
        "home": _brand(emp.business),
        "postings": [{"p": p, "brand": _brand(p.business)} for p in postings],
        "active_count": sum(1 for p in postings if p.is_active),
        "login": staff.login_of(emp),
        "blockers": staff.login_blockers(emp),
        "syncup_ready": bool(cfg.is_configured and link_base(cfg)),
    })


def _password_page(request, emp, password, issued):
    """The one time this password is shown: rendered straight into the response, never
    stored or put in the session; never_cache on the views keeps it out of caches."""
    login = staff.login_of(emp)
    return render(request, "console/login_password.html", {
        "name": emp.name, "email": login.login_email, "password": password, "issued": issued,
        "back_url": reverse("console_employee", args=[emp.id]),
        "app": "the staff app",
    })


@never_cache
@console_required
@require_POST
def employee_login_issue(request, employee_id):
    emp = get_object_or_404(Employee, id=employee_id)
    try:
        password = staff.issue_login(emp)
    except LoginBlocked as e:
        for reason in e.reasons:
            messages.error(request, reason)
        return _back(emp)
    except SyncUpError as e:
        messages.error(request, "SyncUp didn't accept the login: %s" % e)
        return _back(emp)
    return _password_page(request, emp, password, issued=True)


@never_cache
@console_required
@require_POST
def employee_login_reset(request, employee_id):
    emp = get_object_or_404(Employee, id=employee_id)
    try:
        password = staff.reset_password(emp)
    except LoginBlocked as e:
        for reason in e.reasons:
            messages.error(request, reason)
        return _back(emp)
    except SyncUpError as e:
        messages.error(request, "SyncUp didn't accept the new password: %s" % e)
        return _back(emp)
    return _password_page(request, emp, password, issued=False)


@console_required
@require_POST
def employee_login_deactivate(request, employee_id):
    emp = get_object_or_404(Employee, id=employee_id)
    if staff.login_of(emp).login_status != StaffLogin.LOGIN_ACTIVE:
        messages.error(request, "This employee has no active login.")
    elif staff.deactivate_login(emp):
        messages.success(request, "Login deactivated. Their app link stopped working.")
    else:
        messages.error(request, "Deactivated here, and the app link stopped working, but "
                                "SyncUp couldn't be told. Use Retry sync.")
    return _back(emp)


@console_required
@require_POST
def employee_login_sync(request, employee_id):
    emp = get_object_or_404(Employee, id=employee_id)
    login = staff.login_of(emp)
    if not login.has_login:
        messages.error(request, "This employee has no login to sync.")
        return _back(emp)
    if login.login_status == StaffLogin.LOGIN_INACTIVE and login.syncup_active is not False:
        staff.deactivate_login(emp)                 # a deactivation SyncUp never heard about
    else:
        staff.refresh_login(emp)
    login = staff.login_of(Employee.objects.get(pk=emp.pk))
    if login.syncup_error:
        messages.error(request, "Still out of sync: %s" % login.syncup_error)
    else:
        messages.success(request, "SyncUp is up to date.")
    return _back(emp)
