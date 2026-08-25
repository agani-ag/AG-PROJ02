"""Desktop management of a business's mobile employees (staff of ONE business)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib.auth.models import User

from ..models import (Employee, Customer, Invoice, EmployeePosting,
                      AttendanceLog, SalaryRecord, EmployeeIncentive)
from ..forms import EmployeeForm
from ..mobile_auth import mint_employee_token, mint_customer_token
from ..utils import calculate_employee_salary

import json
import calendar
import datetime
from django.db.models import Sum, Q


def _invoice_total(invoice_json):
    """The grand total stored inside an invoice's JSON (amounts live there, not in columns)."""
    try:
        return round(float(json.loads(invoice_json).get('invoice_total_amt_with_gst', 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _posting(request, posting_id):
    """A posting at the current business — own (home) or shared-in. 404 otherwise."""
    return get_object_or_404(
        EmployeePosting.objects.select_related("employee"),
        pk=posting_id, business=request.user)


@login_required
def employees(request):
    postings = (EmployeePosting.objects.filter(business=request.user)
                .select_related("employee").order_by("-is_home", "employee__name"))
    return render(request, "employees/employees.html", {"postings": postings})


@login_required
def employee_add(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save(commit=False)
            emp.business = request.user
            emp.save()   # auto-creates the home posting
            home = emp.postings.get(is_home=True)
            home.salary = _num(request.POST.get("salary"))
            home.is_admin = bool(request.POST.get("is_admin"))
            home.attendance_eligible = bool(request.POST.get("attendance_eligible"))
            home.is_active = emp.is_active
            home.save()
            messages.success(request, f"Employee '{emp.name}' added.")
            return redirect("employees")
        return render(request, "employees/employee_edit.html", {"error_message": form.errors, "form": form})
    return render(request, "employees/employee_edit.html", {"form": EmployeeForm()})


@login_required
def employee_edit(request, posting_id):
    posting = _posting(request, posting_id)
    emp = posting.employee
    if request.method == "POST":
        # The person's identity is editable only by their HOME business.
        if posting.is_home:
            form = EmployeeForm(request.POST, instance=emp)
            if form.is_valid():
                form.save()
            else:
                return render(request, "employees/employee_edit.html", {
                    "posting": posting, "employee": emp,
                    "error_message": form.errors, "form": form})
        # Per-business posting fields — every business sets these for their own posting.
        posting.salary = _num(request.POST.get("salary"))
        posting.is_admin = bool(request.POST.get("is_admin"))
        posting.is_active = bool(request.POST.get("is_active"))
        posting.attendance_eligible = bool(request.POST.get("attendance_eligible"))
        posting.save()
        messages.success(request, "Saved.")
        return redirect("employees")
    return render(request, "employees/employee_edit.html", {
        "posting": posting, "employee": emp, "form": EmployeeForm(instance=emp)})


@login_required
def employee_add_shared(request):
    """Add a person shared from another business by pasting their employee share code."""
    if request.method != "POST":
        return redirect("employees")
    code = (request.POST.get("share_code") or "").strip().upper()
    emp = Employee.objects.filter(share_code__iexact=code).first()
    if not emp:
        messages.error(request, "No employee found for that code.")
    elif emp.business_id == request.user.id:
        messages.error(request, "That's your own employee.")
    elif EmployeePosting.objects.filter(employee=emp, business=request.user).exists():
        messages.error(request, f"{emp.name} is already in your team.")
    else:
        EmployeePosting.objects.create(employee=emp, business=request.user, is_home=False, is_active=True)
        messages.success(request, f"{emp.name} added as a shared employee.")
    return redirect("employees")


@login_required
def employee_share_lookup(request):
    """Validate a pasted employee share code → the person (for the add-shared UI)."""
    code = (request.GET.get("code") or "").strip().upper()
    emp = Employee.objects.filter(share_code__iexact=code).select_related("business").first()
    if not emp:
        return JsonResponse({"ok": False, "message": "No employee found for that code."})
    if emp.business_id == request.user.id:
        return JsonResponse({"ok": False, "message": "That's your own employee."})
    p = getattr(emp.business, "userprofile", None)
    home = (p.business_brand or p.business_title if p else None) or emp.business.username
    return JsonResponse({"ok": True, "name": emp.name, "home": home})


@login_required
def employee_delete(request, posting_id):
    """Home posting → delete the whole person (cascades all postings + HR). Shared → just
    remove this business's posting (cascades only this business's HR)."""
    if request.method == "POST":
        posting = _posting(request, posting_id)
        if posting.is_home:
            posting.employee.delete()
            messages.success(request, "Employee removed.")
        else:
            posting.delete()
            messages.success(request, "Shared employee removed from your team.")
    return redirect("employees")


@login_required
def employee_invoices(request, posting_id):
    """Invoices raised by THIS business and credited to the posting's person."""
    posting = _posting(request, posting_id)
    emp = posting.employee
    qs = Invoice.objects.filter(user=request.user, assigned_employee=emp).order_by('-invoice_date', '-id')

    months_list = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in qs.dates('invoice_date', 'month', order='DESC')
    ]
    selected_month = request.GET.get('month', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if selected_month:
        try:
            year, month = selected_month.split('-')
            qs = qs.filter(invoice_date__year=int(year), invoice_date__month=int(month))
        except ValueError:
            pass
    if date_from:
        qs = qs.filter(invoice_date__gte=date_from)
    if date_to:
        qs = qs.filter(invoice_date__lte=date_to)

    rows, grand_total = [], 0.0
    for inv in qs.select_related('invoice_customer'):
        amount = _invoice_total(inv.invoice_json)
        grand_total += amount
        rows.append({
            'id': inv.id, 'number': inv.invoice_number, 'date': inv.invoice_date,
            'is_gst': inv.is_gst, 'amount': amount,
            'customer': inv.invoice_customer.customer_name if inv.invoice_customer else 'N/A',
        })

    return render(request, 'employees/employee_invoices.html', {
        'posting': posting, 'employee': emp, 'rows': rows, 'months_list': months_list,
        'selected_month': selected_month, 'date_from': date_from, 'date_to': date_to,
        'grand_total': round(grand_total, 2), 'record_count': len(rows),
    })


@login_required
def employee_invoices_pick(request, posting_id):
    """Invoices of THIS business for the bulk-map picker — searchable, with each one's
    current staff assignment so the admin can see (and change) who it's credited to."""
    posting = _posting(request, posting_id)
    q = (request.GET.get('q') or '').strip()
    qs = (Invoice.objects.filter(user=request.user)
          .select_related('invoice_customer', 'assigned_employee').order_by('-invoice_date', '-id'))
    if q:
        cond = Q(invoice_customer__customer_name__icontains=q)
        if q.isdigit():
            cond |= Q(invoice_number=int(q))
        qs = qs.filter(cond)
    rows = [{
        'id': inv.id, 'number': inv.invoice_number, 'is_gst': inv.is_gst,
        'date': inv.invoice_date.strftime('%d %b %Y') if inv.invoice_date else '',
        'customer': inv.invoice_customer.customer_name if inv.invoice_customer else 'N/A',
        'amount': _invoice_total(inv.invoice_json),
        'assigned': inv.assigned_employee.name if inv.assigned_employee_id else None,
        'mine': inv.assigned_employee_id == posting.employee_id,
    } for inv in qs[:200]]
    return JsonResponse({'rows': rows})


@login_required
def employee_assign_bulk(request, posting_id):
    """Bulk map / unmap invoices to this posting's employee. Body: {map:[ids], unmap:[ids]}.
    Unmap only clears invoices currently credited to THIS employee (never steals a clear)."""
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from django.utils import timezone
    posting = _posting(request, posting_id)
    emp = posting.employee
    try:
        data = json.loads(request.body)
        map_ids = [int(i) for i in (data.get('map') or [])]
        unmap_ids = [int(i) for i in (data.get('unmap') or [])]
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'message': 'Bad request'}, status=400)
    base = Invoice.objects.filter(user=request.user)
    mapped = base.filter(id__in=map_ids).update(
        assigned_employee=emp, assigned_employee_at=timezone.now()) if map_ids else 0
    unmapped = base.filter(id__in=unmap_ids, assigned_employee=emp).update(
        assigned_employee=None, assigned_employee_at=None) if unmap_ids else 0
    return JsonResponse({'ok': True, 'mapped': mapped, 'unmapped': unmapped})


@login_required
def employee_mobile_link(request, posting_id):
    """Signed /m/employee/ URL. Only the HOME business issues it — the person has one login."""
    posting = _posting(request, posting_id)
    if not posting.is_home:
        return JsonResponse({"ok": False, "message": "Only the home business issues the mobile link."})
    emp = posting.employee
    url = request.build_absolute_uri("/m/employee/") + "?t=" + mint_employee_token(emp)
    return JsonResponse({"ok": True, "url": url, "name": emp.name, "email": emp.email})


@login_required
def employee_revoke(request, posting_id):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    posting = _posting(request, posting_id)
    if not posting.is_home:
        return JsonResponse({"ok": False, "message": "Only the home business can revoke the login."})
    emp = posting.employee
    emp.token_version += 1
    emp.save()
    return JsonResponse({"ok": True})


@login_required
def customer_mobile_link(request, customer_id):
    """Signed /m/customer/ URL to paste into this customer's SyncUp link list."""
    c = get_object_or_404(Customer, id=customer_id, user=request.user)
    url = request.build_absolute_uri("/m/customer/") + "?t=" + mint_customer_token(c)
    return JsonResponse({"ok": True, "url": url})


# ============ Attendance & Salary / Incentive (desktop, per posting) =============

def _sel_year_month(request):
    today = datetime.date.today()
    try:
        year = int(request.GET.get("year") or today.year)
        month = int(request.GET.get("month") or today.month)
        if not (1 <= month <= 12):
            month = today.month
    except (ValueError, TypeError):
        year, month = today.year, today.month
    return year, month


def _shift_month(year, month, delta):
    m = month - 1 + delta
    return {"year": year + m // 12, "month": m % 12 + 1}


@login_required
def employee_salary(request, posting_id):
    """Attendance calendar + salary for one posting (this business's record of the person)."""
    posting = _posting(request, posting_id)
    emp = posting.employee
    if not posting.attendance_eligible:
        return render(request, "employees/employee_salary.html", {
            "posting": posting, "employee": emp, "not_eligible": True})
    year, month = _sel_year_month(request)

    if request.method == "POST":
        try:
            advances = float(request.POST.get("advances") or 0)
            bonus = float(request.POST.get("bonus") or 0)
        except (ValueError, TypeError):
            messages.error(request, "Enter valid numbers.")
            return redirect(f"{request.path}?year={year}&month={month}")
        calculate_employee_salary(posting, year, month, advances=advances, bonus=bonus)
        messages.success(request, "Saved.")
        return redirect(f"{request.path}?year={year}&month={month}")

    logs = {l.date: l for l in AttendanceLog.objects.filter(
        posting=posting, date__year=year, date__month=month)}
    first_wd, days_in_month = calendar.monthrange(year, month)
    lead = (first_wd + 1) % 7
    cells = [None] * lead
    for d in range(1, days_in_month + 1):
        dt = datetime.date(year, month, d)
        lg = logs.get(dt)
        cells.append({"day": d, "date": dt.isoformat(),
                      "status": lg.status if lg else None,
                      "status_label": lg.get_status_display() if lg else ""})
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]

    counts = {"present": 0, "absent": 0, "half": 0, "leave": 0}
    for lg in logs.values():
        counts[{0: "present", 1: "absent", 2: "half", 3: "leave"}[lg.status]] += 1
    counts["unmarked"] = days_in_month - len(logs)
    record = calculate_employee_salary(posting, year, month)

    from decimal import Decimal
    per_day = (record.base_salary / record.total_days) if record.total_days else Decimal(0)
    amounts = {
        "per_day": per_day,
        "present": counts["present"] * per_day,
        "half": Decimal(str(counts["half"])) * Decimal("0.5") * per_day,
        "leave": counts["leave"] * per_day,
        "unpaid": (counts["absent"] + counts["unmarked"]) * per_day,
        "earned": record.base_salary - record.deduction,
    }
    history = SalaryRecord.objects.filter(posting=posting).exclude(month=month, year=year)[:12]
    return render(request, "employees/employee_salary.html", {
        "posting": posting, "employee": emp, "year": year, "month": month,
        "month_name": calendar.month_name[month], "weeks": weeks, "counts": counts,
        "record": record, "amounts": amounts, "history": history,
        "prev": _shift_month(year, month, -1), "next": _shift_month(year, month, 1),
    })


@login_required
def attendance_mark(request, posting_id):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    posting = _posting(request, posting_id)
    if not posting.attendance_eligible:
        return JsonResponse({"ok": False, "message": "Not on attendance."}, status=400)
    try:
        payload = json.loads(request.body)
        dt = datetime.date.fromisoformat(payload["date"])
        status = int(payload["status"])
    except (ValueError, TypeError, KeyError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    if status == -1:
        AttendanceLog.objects.filter(posting=posting, date=dt).delete()
    elif status in dict(AttendanceLog.STATUS_CHOICES):
        AttendanceLog.objects.update_or_create(posting=posting, date=dt, defaults={"status": status})
    else:
        return JsonResponse({"ok": False, "message": "Bad status"}, status=400)
    rec = calculate_employee_salary(posting, dt.year, dt.month)
    return JsonResponse({"ok": True, "net": float(rec.calculated_salary)})


@login_required
def attendance_mark_all(request, posting_id):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    posting = _posting(request, posting_id)
    if not posting.attendance_eligible:
        return JsonResponse({"ok": False, "message": "Not on attendance."}, status=400)
    year, month = _sel_year_month(request)
    days_in_month = calendar.monthrange(year, month)[1]
    for d in range(1, days_in_month + 1):
        AttendanceLog.objects.update_or_create(
            posting=posting, date=datetime.date(year, month, d),
            defaults={"status": AttendanceLog.PRESENT})
    calculate_employee_salary(posting, year, month)
    return JsonResponse({"ok": True})


@login_required
def employee_incentives(request, posting_id):
    posting = _posting(request, posting_id)
    emp = posting.employee
    if request.method == "POST":
        try:
            amount = float(request.POST.get("amount") or 0)
        except (ValueError, TypeError):
            amount = 0
        if amount <= 0:
            messages.error(request, "Enter a valid amount.")
        else:
            d = request.POST.get("date")
            EmployeeIncentive.objects.create(
                posting=posting, amount=amount,
                description=request.POST.get("description") or "",
                date=datetime.date.fromisoformat(d) if d else datetime.date.today(),
                is_paid=bool(request.POST.get("is_paid")))
            messages.success(request, "Incentive added.")
        return redirect("employee_incentives", posting_id=posting.id)
    incentives = EmployeeIncentive.objects.filter(posting=posting)
    agg = incentives.aggregate(total=Sum("amount"))
    paid = incentives.filter(is_paid=True).aggregate(total=Sum("amount"))
    return render(request, "employees/employee_incentives.html", {
        "posting": posting, "employee": emp, "incentives": incentives,
        "total": agg["total"] or 0, "paid": paid["total"] or 0,
        "unpaid": (agg["total"] or 0) - (paid["total"] or 0),
    })


@login_required
def incentive_toggle_paid(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    inc = get_object_or_404(EmployeeIncentive, pk=pk, posting__business=request.user)
    inc.is_paid = not inc.is_paid
    inc.save(update_fields=["is_paid"])
    return JsonResponse({"ok": True, "is_paid": inc.is_paid})


@login_required
def incentive_delete(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    get_object_or_404(EmployeeIncentive, pk=pk, posting__business=request.user).delete()
    return JsonResponse({"ok": True})
