"""Console: issue many app logins in one go.

The page lists the chosen customers or employees and issues their logins from the browser,
two at a time, filling in each password as it arrives. Passwords exist only in that page:
they're never stored, and never_cache keeps it out of caches. Working from the browser
keeps every request short (no web-server timeout however many are chosen), stays well
inside SyncUp's per-minute rate limit, and shows progress as it goes.
"""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from ..console_auth import console_required
from ..models import Employee, Party, StaffLogin, SyncUpSettings


@never_cache
@console_required
@require_POST
def logins_bulk(request):
    kind = request.POST.get("kind")
    ids = [int(v) for v in request.POST.getlist("ids") if v.strip().isdigit()]
    domain = SyncUpSettings.load().login_domain

    if kind == "employee":
        back = reverse("console_employees")
        active = set(StaffLogin.objects.filter(employee_id__in=ids,
                                               login_status=StaffLogin.LOGIN_ACTIVE)
                     .values_list("employee_id", flat=True))
        items = [{"name": e.name, "email": StaffLogin(employee_id=e.id).login_email_at(domain),
                  "url": reverse("console_employee_login_issue_json", args=[e.id])}
                 for e in Employee.objects.filter(id__in=ids).order_by("name")
                 if e.id not in active]
    else:
        kind = "party"
        back = reverse("console_customers") + "?show=mapped"
        items = [{"name": p.name, "email": p.login_email_at(domain),
                  "url": reverse("console_party_login_issue_json", args=[p.id])}
                 for p in Party.objects.filter(id__in=ids)
                 .exclude(login_status=Party.LOGIN_ACTIVE).order_by("name", "id")]

    if not items:
        messages.error(request, "Tick at least one without an active login.")
        return redirect(back)
    return render(request, "console/logins_bulk.html",
                  {"items": items, "kind": kind, "back_url": back})
