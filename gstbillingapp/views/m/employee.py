"""Employee / field-staff mobile web screens (/m/employee/...) — lean, WebView-served."""
import json
import datetime

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404

from ...mobile_auth import mobile_login_required
from ...models import Customer, Book, BookLog, Invoice, Quotation
from ...utils import recalculate_book_current_balance


def _user(request):
    # The business this employee is scoped to (the owner's User).
    return request.mobile_actor["user"]


def _emp(request):
    return request.mobile_actor.get("employee")


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
    books = Book.objects.filter(user=u)
    due_total = sum(-float(b.current_balance) for b in books if (b.current_balance or 0) < 0)
    due_count = sum(1 for b in books if (b.current_balance or 0) < 0)
    return render(request, "m/e/home.html", {
        "profile": getattr(u, "userprofile", None), "today": today, "uid": u.id,
        "employee": _emp(request),
        "sales": round(sales, 2), "coll": round(coll, 2),
        "inv_count": invs.count(),
        "cust_count": Customer.objects.filter(user=u).count(),
        "due_total": round(due_total, 2), "due_count": due_count,
    })


@mobile_login_required("employee")
def customers(request):
    u = _user(request)
    balances = {b.customer_id: float(b.current_balance or 0) for b in Book.objects.filter(user=u)}
    rows = [{
        "id": c.id, "name": c.customer_name, "phone": c.customer_phone,
        "bal": balances.get(c.id, 0.0),
    } for c in Customer.objects.filter(user=u).order_by("customer_name")]
    return render(request, "m/e/customers.html", {"rows": rows})


@mobile_login_required("employee")
def customer_detail(request, customer_id):
    u = _user(request)
    c = get_object_or_404(Customer, id=customer_id, user=u)
    book = Book.objects.filter(user=u, customer=c).first()
    logs = list(BookLog.objects.filter(parent_book=book, is_active=True)
                .order_by("-date", "-id")[:60]) if book else []
    bal = float(book.current_balance) if book else 0.0
    return render(request, "m/e/customer_detail.html", {
        "c": c, "logs": logs, "balance": bal,
        "outstanding": round(-bal, 2) if bal < 0 else 0.0,
    })


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
    emp = _emp(request)
    book, _ = Book.objects.get_or_create(user=u, customer=c)
    log = BookLog(parent_book=book, change_type=0, change=amount,
                  description=(data.get("note") or "Payment (mobile)"),
                  createdby=(emp.name if emp else u.username))
    log.save()
    recalculate_book_current_balance(book)
    book.last_log = log
    book.save()
    return JsonResponse({"ok": True, "balance": float(book.current_balance)})


@mobile_login_required("employee")
def invoices(request):
    u = _user(request)
    rows = [{
        "id": inv.id, "number": inv.invoice_number, "date": inv.invoice_date,
        "amount": _inv_total(inv.invoice_json), "is_gst": inv.is_gst,
        "customer": inv.invoice_customer.customer_name if inv.invoice_customer else "N/A",
    } for inv in Invoice.objects.filter(user=u).select_related("invoice_customer")
                 .order_by("-invoice_date", "-id")[:100]]
    return render(request, "m/e/invoices.html", {"rows": rows})


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
def orders(request):
    u = _user(request)
    rows = list(Quotation.objects.filter(user=u).select_related("quotation_customer")
                .order_by("-quotation_date", "-id")[:100])
    return render(request, "m/e/orders.html", {"rows": rows})
