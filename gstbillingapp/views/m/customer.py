"""Customer mobile web screens (/m/customer/...) — lean, WebView-served."""
import json

from django.shortcuts import render, get_object_or_404

from ...mobile_auth import mobile_login_required
from ...models import Book, BookLog, Invoice, Quotation


def _cust(request):
    return request.mobile_actor["customer"]


def _inv_total(js):
    try:
        return round(float(json.loads(js).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


@mobile_login_required("customer")
def home(request):
    from django.db.models import Sum
    from datetime import date

    actor = request.mobile_actor
    siblings = actor["siblings"]           # {business_id: Customer}
    month_start = date.today().replace(day=1)

    books = Book.objects.filter(customer__in=list(siblings.values()))
    logs = BookLog.objects.filter(parent_book__in=books, is_active=True)

    def _sum(qs):
        return float(qs.aggregate(s=Sum("change"))["s"] or 0)

    purchased = -_sum(logs.filter(change_type=1))          # type 1 stored negative
    paid = _sum(logs.filter(change_type=0))
    returned = _sum(logs.filter(change_type=2))
    m_logs = logs.filter(date__date__gte=month_start)
    m_purchased = -_sum(m_logs.filter(change_type=1))
    m_paid = _sum(m_logs.filter(change_type=0))

    per, group_total = [], 0.0
    for b in actor["businesses"]:
        cust = siblings.get(b.id)
        book = Book.objects.filter(user=b, customer=cust).first() if cust else None
        bal = float(book.current_balance) if book else 0.0
        due = round(-bal, 2) if bal < 0 else 0.0
        group_total += due
        prof = getattr(b, "userprofile", None)
        per.append({
            "id": b.id, "due": due,
            "title": (prof.business_title if prof else None) or b.username,
            "brand": prof.business_brand if prof else None,
        })

    return render(request, "m/c/home.html", {
        "primary": actor["primary"], "multi": actor["multi"],
        "per": per, "group_total": round(group_total, 2),
        "purchased": round(purchased, 2), "paid": round(paid, 2), "returned": round(returned, 2),
        "m_purchased": round(m_purchased, 2), "m_paid": round(m_paid, 2),
        "m_pcount": m_logs.filter(change_type=1).count(),
        "m_paycount": m_logs.filter(change_type=0).count(),
        "progress": round(paid / purchased * 100) if purchased > 0 else 0,
        "m_progress": round(m_paid / m_purchased * 100) if m_purchased > 0 else 0,
    })


@mobile_login_required("customer")
def books(request):
    c = _cust(request)
    book = Book.objects.filter(user=c.user, customer=c).first()
    logs = list(BookLog.objects.filter(parent_book=book, is_active=True)
                .order_by("-date", "-id")[:100]) if book else []
    bal = float(book.current_balance) if book else 0.0
    return render(request, "m/c/books.html", {
        "c": c, "logs": logs, "balance": bal,
        "outstanding": round(-bal, 2) if bal < 0 else 0.0,
        "advance": round(bal, 2) if bal > 0 else 0.0,
    })


@mobile_login_required("customer")
def invoices(request):
    c = _cust(request)
    rows = [{
        "id": inv.id, "number": inv.invoice_number, "date": inv.invoice_date,
        "amount": _inv_total(inv.invoice_json), "is_gst": inv.is_gst,
    } for inv in Invoice.objects.filter(user=c.user, invoice_customer=c)
                 .order_by("-invoice_date", "-id")[:100]]
    return render(request, "m/c/invoices.html", {"c": c, "rows": rows})


@mobile_login_required("customer")
def invoice_detail(request, invoice_id):
    c = _cust(request)
    inv = get_object_or_404(Invoice, id=invoice_id, invoice_customer=c, user=c.user)
    try:
        data = json.loads(inv.invoice_json)
    except (ValueError, TypeError):
        data = {"items": []}
    return render(request, "m/c/invoice_detail.html", {
        "c": c, "inv": inv, "d": data, "profile": getattr(c.user, "userprofile", None),
    })


@mobile_login_required("customer")
def orders(request):
    c = _cust(request)
    rows = list(Quotation.objects.filter(user=c.user, quotation_customer=c)
                .order_by("-quotation_date", "-id")[:100])
    return render(request, "m/c/orders.html", {"c": c, "rows": rows})


@mobile_login_required("customer")
def profile(request):
    return render(request, "m/c/profile.html", {"c": _cust(request)})
