"""Shared server-side pagination + search for the mobile list screens.

Each list view renders page 1 server-side; a companion *_data endpoint returns the
next page (or a fresh search/filter result) as rendered row HTML + a has_more flag,
which the `data-mpaged` component in m/base.html appends or swaps in.
"""
import json

from django.db.models import Q, Sum

PAGE = 30

# Icon-chip palette; a customer always maps to the same colour (by their id), so their
# invoices are visually grouped and consistent across pages/reloads.
PALETTE = ["ic-blue", "ic-teal", "ic-purple", "ic-green", "ic-amber", "ic-pink"]


def customer_color(customer_id):
    return PALETTE[(customer_id or 0) % len(PALETTE)]


def _int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _inv_total(js):
    try:
        return round(float(json.loads(js).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


def invoice_page(qs, offset, q, employee=None):
    """(rows, has_more) for an invoice queryset, filtered by search text `q`.

    Searches customer name (partial) and, when `q` is numeric, the exact number.
    """
    q = (q or "").strip()
    if q:
        cond = Q(invoice_customer__customer_name__icontains=q)
        if q.isdigit():
            cond |= Q(invoice_number=int(q))
        qs = qs.filter(cond)
    offset = _int(offset)
    window = list(qs[offset:offset + PAGE + 1])
    has_more = len(window) > PAGE
    rows = [{
        "id": inv.id, "number": inv.invoice_number, "date": inv.invoice_date,
        "amount": _inv_total(inv.invoice_json), "is_gst": inv.is_gst,
        "customer": inv.invoice_customer.customer_name if inv.invoice_customer else "N/A",
        "color": customer_color(inv.invoice_customer_id),
        "mine": employee is not None and inv.assigned_employee_id == employee.id,
    } for inv in window[:PAGE]]
    return rows, has_more


def ledger_page(qs, offset, ctype):
    """(logs, has_more, total) for a BookLog queryset filtered by mode.

    `total` is the Indian-formatted sum for the selected mode (for the frozen total
    bar), or None when showing all modes.
    """
    from ...templatetags.money import format_inr
    total = None
    ctype = (ctype or "all")
    if ctype != "all" and ctype.isdigit():
        qs = qs.filter(change_type=int(ctype))
        total = format_inr(abs(qs.aggregate(s=Sum("change"))["s"] or 0), 2)
    offset = _int(offset)
    window = list(qs[offset:offset + PAGE + 1])
    has_more = len(window) > PAGE
    return window[:PAGE], has_more, total
