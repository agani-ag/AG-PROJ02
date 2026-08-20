"""
Original-invoice viewer for mobile actors (/m/invoice/<id>/print).

Serves the SAME document as the desktop invoice printer — full letterhead,
bank/UPI block, tax table, signature — but authenticated by the signed mobile
token instead of a Django login, so customers and employees can view / print /
save-as-PDF the real invoice from the WebView.

Scoping: a customer only reaches invoices raised against them; an employee only
reaches invoices of their business. Anything else 404s.
"""
import json

import num2words
from django.shortcuts import get_object_or_404, render

from ...mobile_auth import mobile_login_required
from ...models import Invoice


@mobile_login_required()
def invoice_print(request, invoice_id):
    actor = request.mobile_actor
    if actor["role"] == "customer":
        c = actor["customer"]
        inv = get_object_or_404(Invoice, id=invoice_id, invoice_customer=c, user=c.user)
    else:
        u = actor["user"]
        inv = get_object_or_404(Invoice, id=invoice_id, user=u)

    try:
        data = json.loads(inv.invoice_json)
    except (ValueError, TypeError):
        data = {}

    try:
        words = num2words.num2words(
            int(data.get("invoice_total_amt_with_gst", 0)), lang="en_IN"
        ).title()
    except (ValueError, TypeError):
        words = ""

    return render(request, "invoices/invoice_printer.html", {
        "invoice": inv,
        "invoice_data": data,
        "currency": "₹",
        "total_in_words": words,
        "user_profile": getattr(inv.user, "userprofile", None),
        "nav_hide": "1",
        "assigned_employee": None,
        "has_employees": False,
        "debug_mode": False,
        "mobile": True,
    })
