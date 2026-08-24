"""Employee / field-staff mobile web screens (/m/employee/...) — lean, WebView-served."""
import json
import datetime

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt

from django.db.models import Sum, Case, When, F, FloatField

from ...mobile_auth import mobile_login_required
from ...models import (Customer, Book, BookLog, Invoice, Quotation, ExpenseTracker,
                       Employee, SalaryRecord, EmployeeIncentive)
from ...utils import recalculate_book_current_balance, round_to_rupee, calculate_employee_salary
from ...templatetags.money import format_inr
from ._paged import PAGE, invoice_page, ledger_page


def _user(request):
    # The business this employee is scoped to (the owner's User).
    return request.mobile_actor["user"]


def _book_totals(log_qs):
    """All four ledger movement totals (as positive numbers) for a BookLog queryset."""
    a = log_qs.aggregate(
        purchases=Sum(Case(When(change_type=1, then=F("change")), output_field=FloatField())),
        payments=Sum(Case(When(change_type=0, then=F("change")), output_field=FloatField())),
        returns=Sum(Case(When(change_type=2, then=F("change")), output_field=FloatField())),
        others=Sum(Case(When(change_type=3, then=F("change")), output_field=FloatField())),
    )
    return {k: abs(a[k] or 0) for k in a}


def _emp(request):
    return request.mobile_actor.get("employee")


def _brand_nav(request, c):
    """The SAME customer across the employee's covered businesses, for a customer-scoped
    screen's brand switcher. Each entry carries that brand's own customer id, so switching
    brand opens the right record instead of reusing this brand's id (which 404s).

    A brand where this customer doesn't exist is simply omitted — so the switcher only
    offers brands that actually have them, and hides entirely when only one does. Matching
    is by phone, else GST, else exact name (all strong keys for these SMB customers)."""
    businesses = request.mobile_actor.get("businesses", [])
    if len(businesses) < 2:
        return []
    active_id = request.mobile_actor["active_business"].id
    phone = (c.customer_phone or "").strip()
    gst = (c.customer_gst or "").strip()
    name = (c.customer_name or "").strip()
    nav = []
    for b in businesses:
        if b.id == active_id:
            match = c
        else:
            qs = Customer.objects.filter(user=b)
            if phone:
                match = qs.filter(customer_phone=phone).first()
            elif gst:
                match = qs.filter(customer_gst=gst).first()
            else:
                match = qs.filter(customer_name__iexact=name).first()
            if not match:
                continue
        p = getattr(b, "userprofile", None)
        nav.append({
            "id": b.id, "cust_id": match.id, "active": b.id == active_id,
            "name": (p.business_brand or p.business_title if p else None) or b.username,
        })
    return nav


def _inv_total(js):
    try:
        return round(float(json.loads(js).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


@mobile_login_required("employee")
def home(request):
    u = _user(request)
    today = datetime.date.today()
    invs = Invoice.objects.filter(user=u, invoice_date=today)
    sales = sum(_inv_total(j) for j in invs.values_list("invoice_json", flat=True))
    pays = BookLog.objects.filter(parent_book__user=u, is_active=True, change_type=0, date__date=today)
    coll = sum(abs(p.change) for p in pays)
    books = list(Book.objects.filter(user=u))
    # Round to paise so a sub-paisa residual reads as cleared — consistent with the
    # customers list, so the "with dues" counts match.
    bal_map = {b.customer_id: round(float(b.current_balance or 0), 2) for b in books}
    due_total = sum(-bal for bal in bal_map.values() if bal < 0)
    due_count = sum(1 for bal in bal_map.values() if bal < 0)

    # Overdue: same FIFO age the customers list uses, gated on actually owing — so this
    # count exactly matches the "Overdue · 90+ days" filter the tile links to.
    od = _overdue_days(u, today)
    overdue_count = sum(1 for cid, bal in bal_map.items() if bal < 0 and od.get(cid, 0) >= 90)
    overdue_amt = sum(-bal for cid, bal in bal_map.items() if bal < 0 and od.get(cid, 0) >= 90)

    # ---- Today's tasks: actionable field-work for the employee ----
    # Customer.DAYS is Sun=0..Sat=6; Python weekday() is Mon=0..Sun=6 → convert.
    model_today = (today.weekday() + 1) % 7
    custs = list(Customer.objects.filter(user=u).only("id", "collection_day", "credit_limit"))
    collect_today_count = collect_today_amt = 0
    for c in custs:
        bal = bal_map.get(c.id, 0.0)
        if c.collection_day == model_today and bal < 0:
            collect_today_count += 1
            collect_today_amt += -bal

    tasks = {
        "collect_today": collect_today_count, "collect_today_amt": format_inr(collect_today_amt, 0),
        "dues_count": due_count, "dues_amt": format_inr(due_total, 0),
        "overdue_count": overdue_count, "overdue_amt": format_inr(overdue_amt, 0),
    }

    # The full-business dashboard (financials + collections) is admin-only. A regular
    # employee sees today's tally and their task list.
    is_admin = bool(request.mobile_actor.get("is_admin"))
    if not is_admin:
        return render(request, "m/e/home.html", {
            "profile": getattr(u, "userprofile", None), "today": today, "uid": u.id,
            "employee": _emp(request), "is_admin": False,
            "sales": round(sales, 2), "coll": round(coll, 2),
            "inv_count": invs.count(),
            "cust_count": len(custs),
            "due_total": round(due_total, 2), "due_count": due_count,
            "tasks": tasks,
        })

    # ---- Financial overview (all-time) + collection progress, scoped to this business ----
    cur_start = today.replace(day=1)
    last_end = cur_start - datetime.timedelta(days=1)
    last_start = last_end.replace(day=1)

    all_logs = BookLog.objects.filter(parent_book__user=u, is_active=True)
    tot = _book_totals(all_logs)
    cur = _book_totals(all_logs.filter(date__date__gte=cur_start))
    last = _book_totals(all_logs.filter(date__date__gte=last_start, date__date__lt=cur_start))

    balance = tot["purchases"] - (tot["payments"] + tot["returns"] + tot["others"])
    total_invoices = Invoice.objects.filter(user=u).count()
    exp_qs = ExpenseTracker.objects.filter(user=u)
    total_expenses = exp_qs.aggregate(t=Sum("amount"))["t"] or 0
    pending_count = BookLog.objects.filter(parent_book__user=u, is_active=False, change_type=0).count()

    def money(v):
        return format_inr(v, 0)

    def pct(paid, billed):
        return round(min(100.0, paid / billed * 100), 1) if billed > 0 else 0.0

    def fill(p):
        return "fill-green" if p >= 80 else ("fill-blue" if p >= 50 else "fill-red")

    financial = {
        "invoices": format_inr(total_invoices, 0),
        "purchases": money(tot["purchases"]),
        "payments": money(tot["payments"]),
        "returns": money(tot["returns"]),
        "others": money(tot["others"]),
        "balance": money(abs(balance)),
        "balance_receivable": balance >= 0,
        "expenses": money(total_expenses),
        "expense_count": exp_qs.count(),
    }

    collection = []
    for label, m in (("This month", cur), ("Last month", last), ("Overall", tot)):
        p = pct(m["payments"], m["purchases"])
        collection.append({
            "label": label, "pct": p, "fill": fill(p),
            "paid": money(m["payments"]), "billed": money(m["purchases"]),
        })

    return render(request, "m/e/home.html", {
        "profile": getattr(u, "userprofile", None), "today": today, "uid": u.id,
        "employee": _emp(request), "is_admin": True,
        "sales": round(sales, 2), "coll": round(coll, 2),
        "inv_count": invs.count(),
        "cust_count": len(custs),
        "due_total": round(due_total, 2), "due_count": due_count,
        "tasks": tasks, "pending_count": pending_count,
        "financial": financial, "collection": collection,
    })


def _overdue_days(u, today):
    """Age (in days) of each customer's OLDEST still-uncovered purchase, via FIFO — the
    same rule the customer's own home screen uses. Payments + returns + adjustments cover
    purchases oldest-first; the first bill they can't cover is the overdue one, and its age
    drives the Overdue filter's 30/60/90-day buckets. 0 = nothing overdue.

    One pass over the business's active ledger logs (ordered by customer, then date), so the
    whole list costs a single extra query, not one per customer."""
    from collections import defaultdict
    purch = defaultdict(list)   # customer_id -> [(amount, date), ...] oldest-first
    credit = defaultdict(float)  # customer_id -> covering funds (paid + returned + others)
    logs = (BookLog.objects.filter(parent_book__user=u, is_active=True)
            .values_list("parent_book__customer_id", "change_type", "change", "date")
            .order_by("parent_book__customer_id", "date", "id"))
    for cid, ct, change, date in logs:
        if cid is None:
            continue
        if ct == 1:                       # purchase (change stored negative)
            purch[cid].append((abs(change or 0), date))
        else:                             # 0 paid / 2 returned / 3 other (signed)
            credit[cid] += (change or 0)
    od = {}
    for cid, plist in purch.items():
        rem = credit.get(cid, 0.0)
        age = 0
        for amt, d in plist:
            if rem + 0.01 >= amt:      # 1-paisa tolerance: don't let float noise "uncover" a bill
                rem -= amt
            else:
                age = (today - d.date()).days if d else 0
                break
        od[cid] = max(age, 0)
    return od


@mobile_login_required("employee")
def customers(request):
    u = _user(request)
    balances = {b.customer_id: float(b.current_balance or 0) for b in Book.objects.filter(user=u)}
    od = _overdue_days(u, datetime.date.today())
    rows = []
    for c in Customer.objects.filter(user=u).order_by("customer_name"):
        # Round so a sub-paisa residual (e.g. 0.001) reads as cleared, not "₹ 0.00".
        bal = round(balances.get(c.id, 0.0), 2)
        rows.append({
            "id": c.id, "name": c.customer_name, "phone": c.customer_phone, "bal": bal,
            # Overdue only applies to a customer who is actually owing — a cleared / in-advance
            # customer (balance ≥ 0) is never overdue, even if FIFO float noise says otherwise.
            "odays": od.get(c.id, 0) if bal < 0 else 0,
        })
    return render(request, "m/e/customers.html", {"rows": rows})


@mobile_login_required("employee")
def customer_detail(request, customer_id):
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    book = Book.objects.filter(user=u, customer=c).first()
    bal = float(book.current_balance) if book else 0.0
    # Include pending (inactive) entries too, so a staff member sees their just-recorded
    # payment awaiting approval — the template badges them.
    qs = (BookLog.objects.filter(parent_book=book).order_by("-date", "-id")
          if book else BookLog.objects.none())
    logs, has_more, _ = ledger_page(qs, 0, "all")
    return render(request, "m/e/customer_detail.html", {
        "c": c, "logs": logs, "balance": bal, "has_more": has_more,
        "outstanding": round(-bal, 2) if bal < 0 else 0.0,
        "brand_nav": _brand_nav(request, c), "brand_url": "m_employee_customer",
    })


@csrf_exempt
@mobile_login_required("employee")
def record_payment(request, customer_id):
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    try:
        data = json.loads(request.body)
        amount = float(data.get("amount") or 0)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad request"}, status=400)
    if amount <= 0:
        return JsonResponse({"ok": False, "message": "Enter a valid amount"}, status=400)
    amount = round_to_rupee(amount)     # whole-rupee ledger entries
    emp = _emp(request)
    is_admin = bool(request.mobile_actor.get("is_admin"))
    book, _ = Book.objects.get_or_create(user=u, customer=c)
    # An admin's payment posts straight to the ledger; a regular employee's is held
    # inactive (pending) until an admin approves it, so it doesn't move the balance yet.
    log = BookLog(parent_book=book, change_type=0, change=amount,
                  description=(data.get("note") or "Payment (mobile)"),
                  createdby=(emp.name if emp else u.username),
                  is_active=is_admin)
    log.save()
    if is_admin:
        recalculate_book_current_balance(book)
        book.last_log = log
        book.save()
        return JsonResponse({"ok": True, "pending": False, "balance": float(book.current_balance)})
    return JsonResponse({"ok": True, "pending": True,
                         "message": "Payment recorded — pending admin approval."})


@mobile_login_required("employee")
def approvals(request):
    """Admin-only: pending (inactive) mobile payments awaiting approval."""
    if not request.mobile_actor.get("is_admin"):
        return render(request, "m/denied.html", status=403)
    u = _user(request)
    pending = (BookLog.objects.filter(parent_book__user=u, is_active=False, change_type=0)
               .select_related("parent_book__customer").order_by("-date", "-id")[:100])
    rows = [{
        "id": lg.id,
        "customer": lg.parent_book.customer.customer_name if lg.parent_book and lg.parent_book.customer else "—",
        "amount": format_inr(abs(lg.change), 2),
        "by": lg.createdby, "date": lg.date, "note": lg.description,
    } for lg in pending]
    return render(request, "m/e/approvals.html", {"rows": rows})


@csrf_exempt
@mobile_login_required("employee")
def approval_act(request, log_id):
    """Admin-only: approve (activate) or reject (delete) a pending payment."""
    if not request.mobile_actor.get("is_admin"):
        return JsonResponse({"ok": False}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    u = _user(request)
    lg = get_object_or_404(BookLog, id=log_id, parent_book__user=u, is_active=False)
    try:
        action = (json.loads(request.body) or {}).get("action")
    except (ValueError, TypeError):
        action = None
    if action == "approve":
        lg.is_active = True
        lg.save()
        book = lg.parent_book
        recalculate_book_current_balance(book)
        book.last_log = lg
        book.save()
        return JsonResponse({"ok": True, "approved": True})
    if action == "reject":
        lg.delete()
        return JsonResponse({"ok": True, "rejected": True})
    return JsonResponse({"ok": False, "message": "Unknown action"}, status=400)


@mobile_login_required("employee")
def invoices(request):
    u = _user(request)
    emp = _emp(request)
    mine = request.GET.get("mine") == "1"

    # Show the All / Related-to-me toggle only when the employee actually has invoices
    # related to them — otherwise the tab is pointless.
    has_mine = emp is not None and Invoice.objects.filter(user=u, assigned_employee=emp).exists()
    if mine and not has_mine:
        mine = False   # nothing related → fall back to the full list
    rows, has_more = invoice_page(_emp_invoice_qs(u, emp, mine), 0, "", employee=emp)
    return render(request, "m/e/invoices.html", {
        "rows": rows, "mine": mine, "has_more": has_more,
        "show_mine": not mine, "has_mine": has_mine,
    })


def _emp_invoice_qs(u, emp, mine):
    qs = (Invoice.objects.filter(user=u).select_related("invoice_customer")
          .order_by("-invoice_date", "-id"))
    if mine and emp:
        qs = qs.filter(assigned_employee=emp)
    return qs


@mobile_login_required("employee")
def invoices_data(request):
    u = _user(request)
    emp = _emp(request)
    mine = request.GET.get("mine") == "1"
    rows, has_more = invoice_page(_emp_invoice_qs(u, emp, mine),
                                  request.GET.get("offset"), request.GET.get("q"), employee=emp)
    html = render_to_string("m/_invoice_rows.html",
                            {"rows": rows, "link_name": "m_employee_invoice",
                             "show_customer": True, "show_mine": not mine}, request)
    return JsonResponse({"html": html, "added": len(rows), "has_more": has_more})


@mobile_login_required("employee")
def invoice_detail(request, invoice_id):
    u = _user(request)
    inv = get_object_or_404(Invoice, id=invoice_id, user=u)
    try:
        data = json.loads(inv.invoice_json)
    except (ValueError, TypeError):
        data = {"items": []}
    return render(request, "m/e/invoice_detail.html", {
        "inv": inv, "d": data,
        "customer": inv.invoice_customer.customer_name if inv.invoice_customer else "N/A",
        "customer_phone": inv.invoice_customer.customer_phone if inv.invoice_customer else "",
        "profile": getattr(u, "userprofile", None),
    })


@mobile_login_required("employee")
def customer_map(request, customer_id):
    """In-app Leaflet map for a customer. Shows the pin if set; lets the employee
    place/adjust it (tap, drag, or GPS) and save — including first-time capture for
    a customer that has no location yet."""
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    profile = getattr(u, "userprofile", None)
    return render(request, "m/e/customer_map.html", {
        "c": c,
        # Fallback map centre when the customer has no pin yet: the business HQ, else
        # a neutral default. The template only drops a marker once one actually exists.
        "biz_lat": profile.business_latitude if profile else None,
        "biz_lng": profile.business_longitude if profile else None,
        "brand_nav": _brand_nav(request, c), "brand_url": "m_employee_customer_map",
    })


@csrf_exempt
@mobile_login_required("employee")
def customer_set_location(request, customer_id):
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    try:
        data = json.loads(request.body)
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Bad coordinates"}, status=400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({"ok": False, "message": "Coordinates out of range"}, status=400)
    # DecimalField(9,6): keep 6 dp, matching the desktop customer form.
    c.customer_latitude = round(lat, 6)
    c.customer_longitude = round(lng, 6)
    c.save(update_fields=["customer_latitude", "customer_longitude"])
    return JsonResponse({"ok": True, "lat": float(c.customer_latitude), "lng": float(c.customer_longitude)})


@mobile_login_required("employee")
def customer_ledger_data(request, customer_id):
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    book = Book.objects.filter(user=u, customer=c).first()
    qs = (BookLog.objects.filter(parent_book=book).order_by("-date", "-id")
          if book else BookLog.objects.none())
    logs, has_more, total = ledger_page(qs, request.GET.get("offset"), request.GET.get("type"))
    html = render_to_string("m/_ledger_rows.html", {"logs": logs}, request)
    return JsonResponse({"html": html, "added": len(logs), "has_more": has_more, "total": total})


@mobile_login_required("employee")
def collections(request):
    u = _user(request)
    today = datetime.date.today()
    # Customer.DAYS is Sun=0..Sat=6; Python weekday() is Mon=0..Sun=6 → convert.
    model_today = (today.weekday() + 1) % 7
    day = request.GET.get("day")
    sel = int(day) if (day and day.isdigit() and 0 <= int(day) <= 6) else model_today
    balances = {b.customer_id: float(b.current_balance or 0) for b in Book.objects.filter(user=u)}
    cs = Customer.objects.filter(user=u, collection_day=sel).order_by("customer_name")
    rows = [{
        "id": c.id, "name": c.customer_name, "phone": c.customer_phone,
        "place": c.customer_place, "bal": balances.get(c.id, 0.0),
    } for c in cs]
    # Owing customers first (most actionable for a collection run).
    rows.sort(key=lambda r: (r["bal"] >= 0, r["name"]))
    total_due = round(sum(-r["bal"] for r in rows if r["bal"] < 0), 2)
    return render(request, "m/e/collections.html", {
        "rows": rows, "sel": sel, "days": Customer.DAYS, "total_due": total_due,
    })


@mobile_login_required("employee")
def collections_route(request):
    """Optimised collection-run map for a day: HQ → the day's located customers, ordered
    nearest-first (with farthest / reverse toggles), drawn as a real driving route. Only
    customers that have coordinates can be routed; the rest are counted so staff know to
    capture their location."""
    u = _user(request)
    profile = getattr(u, "userprofile", None)
    today = datetime.date.today()
    model_today = (today.weekday() + 1) % 7
    day = request.GET.get("day")
    sel = int(day) if (day and day.isdigit() and 0 <= int(day) <= 6) else model_today
    balances = {b.customer_id: float(b.current_balance or 0) for b in Book.objects.filter(user=u)}
    located, missing = [], 0
    for c in Customer.objects.filter(user=u, collection_day=sel).order_by("customer_name"):
        if c.customer_latitude is not None and c.customer_longitude is not None:
            located.append({
                "id": c.id, "name": c.customer_name, "place": c.customer_place or "",
                "lat": float(c.customer_latitude), "lng": float(c.customer_longitude),
                "bal": round(balances.get(c.id, 0.0), 2),
            })
        else:
            missing += 1
    hq_lat = float(profile.business_latitude) if profile and profile.business_latitude is not None else None
    hq_lng = float(profile.business_longitude) if profile and profile.business_longitude is not None else None
    return render(request, "m/e/collections_route.html", {
        "sel": sel, "day_label": dict(Customer.DAYS).get(sel, ""),
        "located": located, "count": len(located), "missing": missing,
        "hq_lat": hq_lat, "hq_lng": hq_lng,
        "hq_name": (profile.business_brand or profile.business_title) if profile else "HQ",
    })


@mobile_login_required("employee")
def orders(request):
    u = _user(request)
    # Only orders placed through the app — desktop-created quotations stay on the desktop.
    rows = list(Quotation.objects.filter(user=u, created_from_cart=True).select_related("quotation_customer")
                .order_by("-quotation_date", "-id")[:100])
    return render(request, "m/e/orders.html", {"rows": rows})


@mobile_login_required("employee")
def my_pay(request):
    """The employee's own salary + incentives — read-only self-view. Salary is entered by
    the business on desktop; here the employee just sees their monthly pay."""
    emp = _emp(request)
    # Salary/incentives are per the ACTIVE business (posting) — a shared employee sees the
    # pay for whichever business they're currently switched to.
    posting = request.mobile_actor.get("posting")
    eligible = bool(posting and posting.attendance_eligible)
    salary = SalaryRecord.objects.filter(posting=posting).first() if eligible else None
    salary_history = list(SalaryRecord.objects.filter(posting=posting)[:12]) if eligible else []
    salary_total = sum(float(r.calculated_salary) for r in salary_history)
    incentives = list(EmployeeIncentive.objects.filter(posting=posting)[:50]) if posting else []
    inc_total = sum(float(i.amount) for i in incentives)
    inc_unpaid = sum(float(i.amount) for i in incentives if not i.is_paid)

    return render(request, "m/e/pay.html", {
        "employee": emp, "eligible": eligible,
        "salary": salary, "salary_history": salary_history, "salary_total": salary_total,
        "incentives": incentives, "inc_total": inc_total, "inc_unpaid": inc_unpaid,
    })
