# Django imports
import datetime
import json

from django.db.models import Sum
from django.shortcuts import render

from gstbillingapp.models import Invoice, BookLog, Book, Customer, Product


def _inv_total(js):
    """Grand total (with GST) parsed out of a stored invoice_json blob."""
    try:
        return round(float(json.loads(js).get("invoice_total_amt_with_gst", 0) or 0), 2)
    except (ValueError, TypeError, AttributeError):
        return 0.0


# ================= Static Pages ==============================
def landing_page(request):
    # Anonymous visitors get the public marketing page — pure storytelling, no app links.
    if not request.user.is_authenticated:
        return render(request, 'landing_public.html', {})

    # Signed-in owners get their live dashboard.
    context = {}
    u = request.user
    if u.is_authenticated:
        today = datetime.date.today()

        # Today's sales — sum of grand totals on invoices dated today.
        invs_today = Invoice.objects.filter(user=u, invoice_date=today)
        sales_today = sum(_inv_total(j) for j in invs_today.values_list("invoice_json", flat=True))

        # Collected today — customer payments (change_type=0) posted today.
        coll_today = abs(
            BookLog.objects.filter(
                parent_book__user=u, is_active=True, change_type=0, date__date=today
            ).aggregate(t=Sum("change"))["t"] or 0
        )

        # Receivables — customers whose ledger balance is negative owe us that much.
        # Round to paise so a sub-paisa residual reads as cleared (matches the customers list).
        bal_map = {b.customer_id: round(float(b.current_balance or 0), 2) for b in Book.objects.filter(user=u)}
        due_total = sum(-bal for bal in bal_map.values() if bal < 0)
        due_count = sum(1 for bal in bal_map.values() if bal < 0)

        context.update({
            "m_sales_today": round(sales_today, 2),
            "m_coll_today": round(coll_today, 2),
            "m_receivable": round(due_total, 2),
            "m_due_count": due_count,
            "m_customers": Customer.objects.filter(user=u).count(),
            "m_products": Product.objects.filter(user=u).count(),
            "m_invoices": Invoice.objects.filter(user=u).count(),
        })
    return render(request, 'landing_page.html', context)
