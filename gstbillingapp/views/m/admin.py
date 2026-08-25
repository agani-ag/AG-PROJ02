"""Admin-only mobile web screens (/m/employee/manage/...) — the owner's toolkit on the
phone: team (attendance/salary/incentives), expenses & cheques, stock, and reports.

Every view here is gated to an ADMIN posting at the active business. A regular employee
that reaches these URLs gets the standard denied page (or a 403 JSON for AJAX).
"""
import json
import calendar
import datetime
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, F, Q, Case, When, FloatField

from ...mobile_auth import mobile_login_required
from ...models import (Customer, Book, BookLog, Invoice, ExpenseTracker, ChequeLeaf,
                       BankDetails, Inventory, Product, EmployeePosting, AttendanceLog,
                       SalaryRecord, EmployeeIncentive, PurchaseLog, VendorPurchase,
                       UserProfile)
from ...utils import calculate_employee_salary
from ...templatetags.money import format_inr
from .employee import _overdue_days


def _u(request):
    return request.mobile_actor["user"]


def _is_admin(request):
    return bool(request.mobile_actor.get("is_admin"))


def _deny(request, ajax=False):
    if ajax:
        return JsonResponse({"ok": False, "message": "Admins only."}, status=403)
    return render(request, "m/denied.html", {"reason": "expired"}, status=403)


def _posting(request, posting_id):
    """A posting at the ACTIVE business — 404 otherwise."""
    return get_object_or_404(
        EmployeePosting.objects.select_related("employee"),
        pk=posting_id, business=_u(request))


# ===================== Admin hub =====================
@mobile_login_required("employee")
def manage(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    today = datetime.date.today()
    # A few live counts for the hub tiles.
    unpaid_inc = (EmployeeIncentive.objects.filter(posting__business=u, is_paid=False)
                  .aggregate(t=Sum("amount"))["t"] or 0)
    # The switcher here only offers businesses where this person is an ADMIN — Manage is
    # admin-only, so switching to a staff-only business would just be denied.
    emp = request.mobile_actor.get("employee")
    admin_ids = set(EmployeePosting.objects.filter(
        employee=emp, is_admin=True, is_active=True).values_list("business_id", flat=True))
    admin_businesses = [b for b in request.mobile_actor["businesses"] if b.id in admin_ids]
    return render(request, "m/e/manage.html", {
        "profile": getattr(u, "userprofile", None),
        "team_count": EmployeePosting.objects.filter(business=u, is_active=True).count(),
        "unpaid_inc": format_inr(unpaid_inc, 0),
        "admin_businesses": admin_businesses,
        "today": today,
    })


# ===================== Team: attendance / salary / incentives =====================
def _sel_ym(request):
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


@mobile_login_required("employee")
def team(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    postings = (EmployeePosting.objects.filter(business=u)
                .select_related("employee").order_by("-is_home", "employee__name"))
    rows = [{
        "id": p.id, "name": p.employee.name, "is_home": p.is_home, "is_admin": p.is_admin,
        "eligible": p.attendance_eligible, "active": p.is_active,
        "salary": format_inr(p.salary, 0) if p.salary else None,
    } for p in postings]
    return render(request, "m/e/team.html", {"rows": rows})


@mobile_login_required("employee")
def team_member(request, posting_id):
    if not _is_admin(request):
        return _deny(request)
    posting = _posting(request, posting_id)
    emp = posting.employee
    if not posting.attendance_eligible:
        ctx = {"posting": posting, "employee": emp, "not_eligible": True}
        ctx.update(_incentive_ctx(posting))          # unpack list + totals, don't nest the dict
        return render(request, "m/e/team_member.html", ctx)

    year, month = _sel_ym(request)
    logs = {l.date: l for l in AttendanceLog.objects.filter(
        posting=posting, date__year=year, date__month=month)}
    first_wd, days_in_month = calendar.monthrange(year, month)
    lead = (first_wd + 1) % 7          # Sun-first grid
    cells = [None] * lead
    for d in range(1, days_in_month + 1):
        dt = datetime.date(year, month, d)
        lg = logs.get(dt)
        cells.append({"day": d, "date": dt.isoformat(), "status": lg.status if lg else None})
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]

    counts = {"present": 0, "absent": 0, "half": 0, "leave": 0}
    for lg in logs.values():
        counts[{0: "present", 1: "absent", 2: "half", 3: "leave"}[lg.status]] += 1
    counts["unmarked"] = days_in_month - len(logs)
    record = calculate_employee_salary(posting, year, month)

    ctx = {
        "posting": posting, "employee": emp, "year": year, "month": month,
        "month_name": calendar.month_name[month], "weeks": weeks, "counts": counts,
        "record": record,
        "prev": _shift_month(year, month, -1), "next": _shift_month(year, month, 1),
    }
    ctx.update(_incentive_ctx(posting))
    return render(request, "m/e/team_member.html", ctx)


def _incentive_ctx(posting):
    incs = list(EmployeeIncentive.objects.filter(posting=posting)[:50])
    total = sum(float(i.amount) for i in incs)
    unpaid = sum(float(i.amount) for i in incs if not i.is_paid)
    return {"incentives": incs, "inc_total": format_inr(total, 0),
            "inc_unpaid": format_inr(unpaid, 0)}


@csrf_exempt
@mobile_login_required("employee")
def team_attendance_mark(request, posting_id):
    if not _is_admin(request):
        return _deny(request, ajax=True)
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
    return JsonResponse({"ok": True, "net": format_inr(rec.calculated_salary, 0),
                         "deduction": format_inr(rec.deduction, 0)})


@csrf_exempt
@mobile_login_required("employee")
def team_salary_save(request, posting_id):
    """Set this month's advances / bonus and recompute net pay."""
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    posting = _posting(request, posting_id)
    year, month = _sel_ym(request)
    try:
        payload = json.loads(request.body)
        advances = float(payload.get("advances") or 0)
        bonus = float(payload.get("bonus") or 0)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Enter valid numbers"}, status=400)
    rec = calculate_employee_salary(posting, year, month, advances=advances, bonus=bonus)
    return JsonResponse({"ok": True, "net": format_inr(rec.calculated_salary, 0)})


@csrf_exempt
@mobile_login_required("employee")
def team_incentive_add(request, posting_id):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    posting = _posting(request, posting_id)
    try:
        payload = json.loads(request.body)
        amount = float(payload.get("amount") or 0)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    if amount <= 0:
        return JsonResponse({"ok": False, "message": "Enter a valid amount"}, status=400)
    EmployeeIncentive.objects.create(
        posting=posting, amount=amount,
        description=(payload.get("description") or "")[:200],
        date=datetime.date.today(),
        is_paid=bool(payload.get("is_paid")))
    return JsonResponse({"ok": True})


@csrf_exempt
@mobile_login_required("employee")
def team_incentive_toggle(request, pk):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    inc = get_object_or_404(EmployeeIncentive, pk=pk, posting__business=_u(request))
    inc.is_paid = not inc.is_paid
    inc.save(update_fields=["is_paid"])
    return JsonResponse({"ok": True, "is_paid": inc.is_paid})


# ===================== Expenses / Cheques / Banks =====================
@mobile_login_required("employee")
def expenses(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    today = datetime.date.today()
    month_start = today.replace(day=1)
    qs = ExpenseTracker.objects.filter(user=u).order_by("-date", "-id")
    month_total = (qs.filter(date__gte=month_start).aggregate(t=Sum("amount"))["t"] or 0)
    rows = [{
        "id": e.id, "amount": format_inr(e.amount, 2), "category": e.category,
        "reference": e.reference, "date": e.date, "notes": e.notes,
    } for e in qs[:100]]
    cats = list(ExpenseTracker.objects.filter(user=u).values_list("category", flat=True)
                .distinct().order_by("category"))
    return render(request, "m/e/expenses.html", {
        "rows": rows, "month_total": format_inr(month_total, 0),
        "month_name": today.strftime("%B"), "categories": cats,
    })


@csrf_exempt
@mobile_login_required("employee")
def expense_add(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _u(request)
    try:
        payload = json.loads(request.body)
        amount = float(payload.get("amount") or 0)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    if amount <= 0:
        return JsonResponse({"ok": False, "message": "Enter a valid amount"}, status=400)
    category = (payload.get("category") or "GENERAL").strip() or "GENERAL"
    reference = (payload.get("reference") or category).strip() or category
    d = payload.get("date")
    ExpenseTracker.objects.create(
        user=u, amount=amount, category=category, reference=reference,
        notes=(payload.get("notes") or "")[:500],
        date=datetime.date.fromisoformat(d) if d else datetime.date.today())
    return JsonResponse({"ok": True})


@mobile_login_required("employee")
def cheques(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    OPEN = ("ISSUED", "PRESENTED")
    today = datetime.date.today()
    allqs = ChequeLeaf.objects.filter(user=u)
    # Split by clearance date: FUTURE = due today or later (post-dated / upcoming), PAST = before today.
    future_count = allqs.filter(clearance_date__gte=today).count()
    past_count = allqs.filter(clearance_date__lt=today).count()
    when = request.GET.get("when")
    if when not in ("past", "future"):
        # Smart default: land on Future when there's anything upcoming, else Past.
        when = "future" if future_count >= 1 else "past"
    if when == "future":
        qs = allqs.filter(clearance_date__gte=today).order_by("clearance_date", "-id")   # soonest first
    else:
        qs = allqs.filter(clearance_date__lt=today).order_by("-clearance_date", "-id")   # most recent first
    rows = [{
        "number": ch.cheque_number, "status": ch.status, "status_label": ch.get_status_display(),
        "amount": format_inr(ch.amount, 2) if ch.amount else None,
        "payee": ch.payee_name, "bank": ch.bank,
        "issue_date": ch.issue_date, "clearance_date": ch.clearance_date,
        "open": ch.status in OPEN, "bounced": ch.status == "BOUNCED",
    } for ch in qs[:150]]
    outstanding = (allqs.filter(status__in=OPEN).aggregate(t=Sum("amount"))["t"] or 0)
    return render(request, "m/e/cheques.html", {
        "rows": rows, "outstanding": format_inr(outstanding, 0),
        "open_count": allqs.filter(status__in=OPEN).count(),
        "when": when, "future_count": future_count, "past_count": past_count,
    })


@mobile_login_required("employee")
def banks(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    rows = list(BankDetails.objects.filter(user=u, whom_account=0).order_by("bank_name"))
    return render(request, "m/e/banks.html", {"rows": rows})


# ===================== Inventory / Products =====================
@mobile_login_required("employee")
def inventory(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    low_only = request.GET.get("low") == "1"
    q = (request.GET.get("q") or "").strip()
    qs = (Inventory.objects.filter(user=u).select_related("product")
          .order_by("product__model_no"))
    if low_only:
        qs = qs.filter(alert_level__gt=0, current_stock__lte=F("alert_level"))
    if q:
        qs = qs.filter(Q(product__model_no__icontains=q) | Q(product__product_name__icontains=q))
    rows = []
    for inv in qs[:400]:
        p = inv.product
        low = inv.alert_level > 0 and inv.current_stock <= inv.alert_level
        rows.append({
            "model_no": p.model_no if p else "—", "name": p.product_name if p else "",
            "stock": inv.current_stock, "alert": inv.alert_level, "low": low,
        })
    low_count = Inventory.objects.filter(user=u, alert_level__gt=0,
                                         current_stock__lte=F("alert_level")).count()
    return render(request, "m/e/inventory.html", {
        "rows": rows, "low_only": low_only, "low_count": low_count, "q": q,
    })


@mobile_login_required("employee")
def products(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    from ...models import ProductCategory
    # Admin-only screen, so it MAY include the cost price (product_purchase_rate) —
    # unlike cart_product_payload(), which must never expose cost to a buyer's cart.
    fields = ("id", "model_no", "product_name", "product_hsn",
              "product_rate_with_gst", "product_gst_percentage", "product_discount",
              "product_category_id", "product_division_category",
              "product_model_category", "product_colour", "product_purchase_rate")
    products = list(Product.objects.filter(user=u).values(*fields))
    categories = list(ProductCategory.objects.filter(user=u).values("id", "category_name"))
    return render(request, "m/e/products.html", {
        "products_json": json.dumps(products, default=str),
        "categories_json": json.dumps(categories),
        "count": len(products),
        "show_cost": True,
    })


# ===================== Vendors & purchase logs =====================
# A purchase log entry: 0 Paid · 1 Purchase · 2 Return · 3 Other. Vendor balance =
# purchased − (paid + returned + others): positive means we still owe the vendor.
_PLOG_TYPE = {0: ("Paid", "green"), 1: ("Purchase", "red"),
              2: ("Return", "amber"), 3: ("Other", "blue")}


def _plog_agg(qs):
    t = qs.aggregate(
        purchased=Sum(Case(When(change_type=1, then=F("change")), output_field=FloatField())),
        paid=Sum(Case(When(change_type=0, then=F("change")), output_field=FloatField())),
        returned=Sum(Case(When(change_type=2, then=F("change")), output_field=FloatField())),
        others=Sum(Case(When(change_type=3, then=F("change")), output_field=FloatField())),
    )
    return {k: abs(t[k] or 0) for k in t}


def _brand(u):
    p = getattr(u, "userprofile", None)
    return (p.business_brand or p.business_title if p else None) or u.username


def _plog_rows(logs, with_vendor=False, brand=None):
    rows = []
    for l in logs:
        label, color = _PLOG_TYPE.get(l.change_type, ("Other", "blue"))
        row = {"type": label, "color": color, "amount": format_inr(abs(l.change), 2),
               "date": l.date, "reference": l.reference, "category": l.category}
        if with_vendor:
            # A vendorless entry is attributed to the business's own brand.
            row["vendor"] = l.vendor.vendor_name if l.vendor else (brand or "Own brand")
            row["own"] = l.vendor is None
        rows.append(row)
    return rows


@mobile_login_required("employee")
def vendors(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    # Per-vendor balance in one grouped query.
    agg = (PurchaseLog.objects.filter(user=u).values("vendor_id").annotate(
        purchased=Sum(Case(When(change_type=1, then=F("change")), output_field=FloatField())),
        paid=Sum(Case(When(change_type=0, then=F("change")), output_field=FloatField())),
        returned=Sum(Case(When(change_type=2, then=F("change")), output_field=FloatField())),
        others=Sum(Case(When(change_type=3, then=F("change")), output_field=FloatField())),
    ))
    bal = {}
    for r in agg:
        bal[r["vendor_id"]] = round(abs(r["purchased"] or 0)
                                    - (abs(r["paid"] or 0) + abs(r["returned"] or 0) + abs(r["others"] or 0)), 2)
    rows = [{
        "id": v.id, "name": v.vendor_name, "phone": v.vendor_phone,
        "balance": bal.get(v.id, 0.0),
    } for v in VendorPurchase.objects.filter(user=u).order_by("vendor_name")]
    payable = sum(r["balance"] for r in rows if r["balance"] > 0)
    return render(request, "m/e/vendors.html", {
        "rows": rows, "payable": format_inr(payable, 0),
        "count": len(rows),
    })


@mobile_login_required("employee")
def vendor_detail(request, vendor_id):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    v = get_object_or_404(VendorPurchase, id=vendor_id, user=u)
    qs = PurchaseLog.objects.filter(user=u, vendor=v)
    t = _plog_agg(qs)
    balance = round(t["purchased"] - (t["paid"] + t["returned"] + t["others"]), 2)
    return render(request, "m/e/vendor_detail.html", {
        "v": v, "rows": _plog_rows(qs.order_by("-date", "-id")[:200]),
        "purchased": format_inr(t["purchased"], 2), "paid": format_inr(t["paid"], 2),
        "returned": format_inr(t["returned"], 2), "others": format_inr(t["others"], 2),
        "balance": abs(balance), "balance_fmt": format_inr(abs(balance), 2),
        "payable": balance > 0, "settled": abs(balance) < 0.005,
    })


@mobile_login_required("employee")
def purchase_logs(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    base = PurchaseLog.objects.filter(user=u)
    t = _plog_agg(base)
    outstanding = round(t["purchased"] - (t["paid"] + t["returned"] + t["others"]), 2)
    from ._paged import purchase_log_page
    window, has_more, _ = purchase_log_page(base.order_by("-date", "-id"), 0, "", "all")
    return render(request, "m/e/purchase_logs.html", {
        "rows": _plog_rows(window, with_vendor=True, brand=_brand(u)), "has_more": has_more,
        "purchased": format_inr(t["purchased"], 0), "paid": format_inr(t["paid"], 0),
        "returned": format_inr(t["returned"], 0), "others": format_inr(t["others"], 0),
        "outstanding": format_inr(abs(outstanding), 0), "excess": outstanding < 0,
    })


@mobile_login_required("employee")
def purchase_logs_data(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    u = _u(request)
    from django.template.loader import render_to_string
    from ._paged import purchase_log_page
    qs = PurchaseLog.objects.filter(user=u).order_by("-date", "-id")
    window, has_more, total = purchase_log_page(
        qs, request.GET.get("offset"), request.GET.get("q"), request.GET.get("type"))
    html = render_to_string("m/e/_purchase_rows.html",
                            {"rows": _plog_rows(window, with_vendor=True, brand=_brand(u))}, request)
    return JsonResponse({"html": html, "added": len(window), "has_more": has_more, "total": total})


# ===================== Reports =====================
@mobile_login_required("employee")
def reports(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    today = datetime.date.today()
    balances = {b.customer_id: round(float(b.current_balance or 0), 2)
                for b in Book.objects.filter(user=u)}
    od = _overdue_days(u, today)

    owing = [(cid, -bal) for cid, bal in balances.items() if bal < 0]
    advance = [(cid, bal) for cid, bal in balances.items() if bal > 0]
    outstanding_total = sum(a for _, a in owing)
    advance_total = sum(a for _, a in advance)

    # Aging buckets by the oldest-uncovered-bill age (FIFO), only for owing customers.
    buckets = {"b0_30": [0.0, 0], "b31_60": [0.0, 0], "b61_90": [0.0, 0], "b90p": [0.0, 0]}
    for cid, amt in owing:
        days = od.get(cid, 0)
        key = ("b90p" if days >= 90 else "b61_90" if days >= 61
               else "b31_60" if days >= 31 else "b0_30")
        buckets[key][0] += amt
        buckets[key][1] += 1

    def bk(k):
        return {"amt": format_inr(buckets[k][0], 0), "count": buckets[k][1]}

    return render(request, "m/e/reports.html", {
        "outstanding": format_inr(outstanding_total, 0), "owing_count": len(owing),
        "advance": format_inr(advance_total, 0), "advance_count": len(advance),
        "aging": {"d0_30": bk("b0_30"), "d31_60": bk("b31_60"),
                  "d61_90": bk("b61_90"), "d90p": bk("b90p")},
        "invoices": Invoice.objects.filter(user=u).count(),
    })


# ===================== Add / Edit forms (admin) =====================
def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _date(v):
    try:
        return datetime.date.fromisoformat(v) if v else datetime.date.today()
    except (TypeError, ValueError):
        return datetime.date.today()


# ---- Bank & UPI ----
@mobile_login_required("employee")
def bank_form(request, pk=0):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    bank = get_object_or_404(BankDetails, pk=pk, user=u, whom_account=0) if pk else None
    return render(request, "m/e/bank_form.html", {"bank": bank})


@csrf_exempt
@mobile_login_required("employee")
def bank_save(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _u(request)
    try:
        d = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    if not (d.get("account_number") or d.get("upi_id")):
        return JsonResponse({"ok": False, "message": "Enter an account number or a UPI ID"}, status=400)
    fields = dict(
        account_name=(d.get("account_name") or "").strip(),
        account_number=(d.get("account_number") or "").strip(),
        bank_name=(d.get("bank_name") or "").strip(),
        branch_name=(d.get("branch_name") or "").strip(),
        ifsc_code=(d.get("ifsc_code") or "").strip(),
        upi_id=(d.get("upi_id") or "").strip(),
        upi_name=(d.get("upi_name") or "").strip(),
    )
    pk = d.get("id")
    if pk:
        bank = get_object_or_404(BankDetails, pk=pk, user=u, whom_account=0)
        for k, v in fields.items():
            setattr(bank, k, v)
        bank.save()
    else:
        BankDetails.objects.create(
            user=u, whom_account=0, business_account=getattr(u, "userprofile", None), **fields)
    return JsonResponse({"ok": True, "redirect": "/m/employee/manage/banks"})


@csrf_exempt
@mobile_login_required("employee")
def bank_delete(request, pk):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    get_object_or_404(BankDetails, pk=pk, user=_u(request), whom_account=0).delete()
    return JsonResponse({"ok": True, "redirect": "/m/employee/manage/banks"})


# ---- Cheque ----
@mobile_login_required("employee")
def cheque_form(request):
    if not _is_admin(request):
        return _deny(request)
    return render(request, "m/e/cheque_form.html", {
        "statuses": ChequeLeaf.STATUS_CHOICES, "today": datetime.date.today().isoformat()})


@csrf_exempt
@mobile_login_required("employee")
def cheque_save(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _u(request)
    try:
        d = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    number = (d.get("cheque_number") or "").strip()
    if not number:
        return JsonResponse({"ok": False, "message": "Cheque number is required"}, status=400)
    if ChequeLeaf.objects.filter(cheque_number=number.upper()).exists():
        return JsonResponse({"ok": False, "message": "That cheque number already exists"}, status=400)
    status = d.get("status") if d.get("status") in dict(ChequeLeaf.STATUS_CHOICES) else "ISSUED"
    ChequeLeaf.objects.create(
        user=u, cheque_number=number, status=status,
        amount=_num(d.get("amount")) or None,
        payee_name=(d.get("payee_name") or "").strip(),
        bank=(d.get("bank") or "").strip(), branch=(d.get("branch") or "").strip(),
        account_number=(d.get("account_number") or "").strip(),
        issue_date=_date(d.get("issue_date")), clearance_date=_date(d.get("clearance_date")),
        remarks=(d.get("remarks") or "").strip())
    return JsonResponse({"ok": True, "redirect": "/m/employee/manage/cheques"})


# ---- Purchase log ----
@mobile_login_required("employee")
def purchase_form(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    vendors = list(VendorPurchase.objects.filter(user=u).order_by("vendor_name")
                   .values("id", "vendor_name"))
    return render(request, "m/e/purchase_form.html", {
        "vendors": vendors, "types": PurchaseLog.CHANGE_TYPES, "brand": _brand(u),
        "today": datetime.date.today().isoformat()})


@csrf_exempt
@mobile_login_required("employee")
def purchase_save(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _u(request)
    try:
        d = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    # Vendor is optional — a vendorless entry is a "business brand" purchase log.
    vid = d.get("vendor")
    vendor = VendorPurchase.objects.filter(id=vid, user=u).first() if vid else None
    amount = _num(d.get("amount"))
    if amount <= 0:
        return JsonResponse({"ok": False, "message": "Enter a valid amount"}, status=400)
    try:
        ctype = int(d.get("change_type"))
    except (TypeError, ValueError):
        ctype = 1
    if ctype not in dict(PurchaseLog.CHANGE_TYPES):
        ctype = 1
    PurchaseLog.objects.create(
        user=u, vendor=vendor, change_type=ctype, change=abs(amount),
        reference=(d.get("reference") or "").strip(), category=(d.get("category") or "").strip(),
        date=_date(d.get("date")))
    return JsonResponse({"ok": True, "redirect": "/m/employee/manage/purchases"})


# ---- Settings / business profile ----
@mobile_login_required("employee")
def settings(request):
    if not _is_admin(request):
        return _deny(request)
    u = _u(request)
    return render(request, "m/e/settings.html", {"p": getattr(u, "userprofile", None)})


@csrf_exempt
@mobile_login_required("employee")
def settings_save(request):
    if not _is_admin(request):
        return _deny(request, ajax=True)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _u(request)
    p, _ = UserProfile.objects.get_or_create(user=u)
    try:
        d = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    title = (d.get("business_title") or "").strip()
    if not title:
        return JsonResponse({"ok": False, "message": "Business name is required"}, status=400)
    p.business_title = title
    p.business_brand = (d.get("business_brand") or "").strip()
    p.business_gst = (d.get("business_gst") or "").strip()
    p.business_phone = (d.get("business_phone") or "").strip()
    p.business_email = (d.get("business_email") or "").strip()
    p.business_address = (d.get("business_address") or "").strip()
    p.save()
    return JsonResponse({"ok": True, "redirect": "/m/employee/manage/settings"})
