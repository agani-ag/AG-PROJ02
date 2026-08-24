"""Customer mobile web screens (/m/customer/...) — lean, WebView-served."""
import json
import datetime

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.db.models import Sum, Case, When, F, FloatField, Count, IntegerField, Min, Max

from ...mobile_auth import mobile_login_required
from ...models import Book, BookLog, Invoice, Quotation
from ._paged import PAGE, invoice_page, ledger_page
from ...templatetags.money import format_inr


def _cust(request):
    return request.mobile_actor["customer"]


def _ledger_agg(qs):
    """The four ledger movement totals + counts for a BookLog queryset."""
    return qs.aggregate(
        purchased=Sum(Case(When(change_type=1, then=F("change")), output_field=FloatField())),
        paid=Sum(Case(When(change_type=0, then=F("change")), output_field=FloatField())),
        returned=Sum(Case(When(change_type=2, then=F("change")), output_field=FloatField())),
        others=Sum(Case(When(change_type=3, then=F("change")), output_field=FloatField())),
        pc=Count(Case(When(change_type=1, then=1), output_field=IntegerField())),
        payc=Count(Case(When(change_type=0, then=1), output_field=IntegerField())),
        rc=Count(Case(When(change_type=2, then=1), output_field=IntegerField())),
        oc=Count(Case(When(change_type=3, then=1), output_field=IntegerField())),
    )


def _inv_total(js):
    try:
        return round(float(json.loads(js).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


@mobile_login_required("customer")
def home(request):
    actor = request.mobile_actor
    siblings = actor["siblings"]           # {business_id: Customer}
    today = datetime.date.today()

    # ---- Group hero + per-shop breakdown (all businesses) ----
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

    # ---- Financial detail for the ACTIVE business (like the ledger/invoice screens) ----
    c = actor["customer"]
    logs = BookLog.objects.filter(parent_book__customer=c, is_active=True)

    def _abs(x):
        return abs(x or 0)

    # Year range present in the ledger (e.g. "2025 - 2026"), like the legacy header.
    yr = logs.aggregate(mn=Min("date__year"), mx=Max("date__year"))
    if yr["mn"] and yr["mx"]:
        fy = str(yr["mn"]) if yr["mn"] == yr["mx"] else f"{yr['mn']} - {yr['mx']}"
    else:
        fy = str(today.year)

    t = _ledger_agg(logs)
    purchased, paid = _abs(t["purchased"]), _abs(t["paid"])
    returned, others = _abs(t["returned"]), _abs(t["others"])   # magnitudes, for display only

    # Amount the customer still owes. Every entry keeps its ledger sign here, so a
    # 'Purchase' adds to it, a 'Payment' and 'Return' reduce it, and 'Other' does
    # whichever its sign says — a credit (+) reduces it, a charge (−) ADDS to it.
    # (This equals the book's own current_balance, negated.)
    def net_owed(m):
        return -((m["purchased"] or 0) + (m["returned"] or 0) + (m["others"] or 0))

    balance = net_owed(t) - paid

    cur_start = today.replace(day=1)
    cur = _ledger_agg(logs.filter(date__date__gte=cur_start))

    def m2(v):
        return format_inr(v, 2)

    def m0(v):
        return format_inr(v, 0)

    def pct(p, b):
        return int(min(100, p / b * 100)) if b > 0 else 0

    def fill(p):
        return "fill-green" if p >= 80 else ("fill-blue" if p >= 40 else "fill-red")

    transaction = {
        "purchased": m2(purchased), "purchased_count": t["pc"] or 0,
        "paid": m2(paid), "paid_count": t["payc"] or 0,
        "returned": m2(returned), "returned_count": t["rc"] or 0,
        "others": m2(others), "others_count": t["oc"] or 0,
    }

    # Payment progress and the balance are measured against the net amount owed
    # (purchases, less returns and 'other' credits, plus 'other' charges), so the
    # percentages agree with the outstanding shown elsewhere.
    def prog(label, m):
        net = net_owed(m)
        p = pct(_abs(m["paid"]), net)
        return {"label": label, "pct": p, "fill": fill(p),
                "paid": m0(_abs(m["paid"])), "billed": m0(net)}

    payment_progress = [prog("Current month", cur), prog("Overall", t)]

    net_total = net_owed(t)          # = balance + paid
    overall_pct = pct(paid, net_total)
    balance_overview = {"outstanding": m2(balance), "pct": overall_pct,
                        "fill": fill(overall_pct), "paid": m2(paid), "billed": m2(net_total)}

    # ---- Overdue bills: FIFO — payments/returns/others cover purchases oldest-first;
    #      once they run out, that bill and every later one are overdue. All overdue
    #      bills are rendered; the "90+ days" filter is applied on the client (no reload).
    remaining = paid + returned + others
    overdue, failed, first_remaining = [], False, 0.0
    for lg in logs.filter(change_type=1).order_by("date"):
        amt = abs(lg.change)
        if not failed and remaining >= amt:
            remaining -= amt
            continue
        if not failed:
            failed = True
            first_remaining = remaining     # leftover payment applied to this first bill
        days = (today - lg.date.date()).days if lg.date else 0
        # Amount this bill contributes to the total owed: the first (partially-paid)
        # bill contributes only its still-owed part, the rest their full amount.
        owed = abs(first_remaining - amt) if (not overdue and first_remaining > 0) else amt
        overdue.append({
            "date": lg.date, "days": days, "amount": m2(amt), "owed": round(owed, 2),
            "balance_after": m2(abs(first_remaining - amt)) if (not overdue and first_remaining > 0) else None,
        })
    overdue_amount = sum(o["owed"] for o in overdue)

    return render(request, "m/c/home.html", {
        "primary": actor["primary"], "multi": actor["multi"],
        "per": per, "group_total": round(group_total, 2),
        "fy": fy,
        "transaction": transaction,
        "payment_progress": payment_progress,
        "balance_overview": balance_overview,
        "overdue": overdue,
        "overdue_amount": m2(overdue_amount),
        "overdue_count": len(overdue),
    })


@mobile_login_required("customer")
def books(request):
    c = _cust(request)
    book = Book.objects.filter(user=c.user, customer=c).first()
    bal = float(book.current_balance) if book else 0.0
    logs, has_more, _ = ledger_page(_cust_ledger_qs(c), 0, "all")
    return render(request, "m/c/books.html", {
        "c": c, "logs": logs, "balance": bal, "has_more": has_more,
        "outstanding": round(-bal, 2) if bal < 0 else 0.0,
        "advance": round(bal, 2) if bal > 0 else 0.0,
    })


def _cust_ledger_qs(c):
    # Include inactive (pending-approval) entries too, so the customer sees a payment
    # their rep just recorded — badged "Pending approval" until the shop approves it.
    book = Book.objects.filter(user=c.user, customer=c).first()
    return (BookLog.objects.filter(parent_book=book).order_by("-date", "-id")
            if book else BookLog.objects.none())


@mobile_login_required("customer")
def books_data(request):
    c = _cust(request)
    logs, has_more, total = ledger_page(_cust_ledger_qs(c), request.GET.get("offset"), request.GET.get("type"))
    html = render_to_string("m/_ledger_rows.html", {"logs": logs}, request)
    return JsonResponse({"html": html, "added": len(logs), "has_more": has_more, "total": total})


def _cust_invoice_qs(c):
    return (Invoice.objects.filter(user=c.user, invoice_customer=c)
            .select_related("invoice_customer").order_by("-invoice_date", "-id"))


@mobile_login_required("customer")
def invoices(request):
    c = _cust(request)
    rows, has_more = invoice_page(_cust_invoice_qs(c), 0, "")
    return render(request, "m/c/invoices.html", {"c": c, "rows": rows, "has_more": has_more})


@mobile_login_required("customer")
def invoices_data(request):
    c = _cust(request)
    rows, has_more = invoice_page(_cust_invoice_qs(c), request.GET.get("offset"), request.GET.get("q"))
    html = render_to_string("m/_invoice_rows.html", {"rows": rows, "link_name": "m_customer_invoice"}, request)
    return JsonResponse({"html": html, "added": len(rows), "has_more": has_more})


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
    # Only orders placed through the app — desktop-created quotations stay on the desktop.
    rows = list(Quotation.objects.filter(user=c.user, quotation_customer=c, created_from_cart=True)
                .order_by("-quotation_date", "-id")[:100])
    return render(request, "m/c/orders.html", {"c": c, "rows": rows})


@mobile_login_required("customer")
def profile(request):
    c = _cust(request)
    prof = getattr(c.user, "userprofile", None)
    book = Book.objects.filter(user=c.user, customer=c).first()
    bal = float(book.current_balance) if book else 0.0
    due = round(-bal, 2) if bal < 0 else 0.0
    return render(request, "m/c/profile.html", {
        "c": c,
        "business_title": (prof.business_title if prof else "") or "",
        "business_brand": (prof.business_brand if prof else "") or "",
        "business_phone": (prof.business_phone if prof else "") or "",
        "bank": (prof.bankdetails if prof else None),
        "due": due,
        "due_fmt": format_inr(due, 2) if due else "",
    })
