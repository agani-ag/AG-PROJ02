"""
Business-smart, point-of-billing intelligence endpoints.

These are read-only JSON APIs consumed by the invoice / quotation create screens to
surface the right fact at the moment a bill is being made:

  * customer_insights  — outstanding balance, aging, last payment, cheque risk,
                         collection day, credit-limit headroom, and this customer's
                         own price history / usual order (Groups A & part of B).
  * today_summary      — today's sales & collections and this month's GST collected,
                         for the running tally / set-aside meter (Group C).

Nothing here mutates data; every query is scoped to request.user.
"""

# Django imports
import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

# Models
from ..models import Customer, Book, BookLog, Invoice, ChequeLeaf


def _invoice_total(invoice_json_str):
    """Grand total (with GST) off a stored invoice/quotation JSON blob, safely."""
    try:
        return float(json.loads(invoice_json_str).get('invoice_total_amt_with_gst', 0) or 0)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _oldest_unpaid_days(logs, today):
    """
    FIFO age (in days) of the oldest purchase not yet covered by settlements.

    Purchases are change_type 1 (stored negative); settlements are Paid / Returned /
    Other (types 0, 2, 3). We pay down the oldest purchases first and return the age
    of the first one still open. Mirrors the AR aging report's intent. None if clear.
    """
    purchases = []      # (date, amount) oldest first
    settled = 0.0
    for log in logs:
        if log.change_type == 1 and log.date:
            purchases.append((log.date, abs(log.change)))
        elif log.change_type in (0, 2, 3):
            settled += abs(log.change)

    purchases.sort(key=lambda p: p[0])
    for pdate, amount in purchases:
        if settled >= amount:
            settled -= amount
            continue
        # This purchase is (partly) still open — its age is the overdue age.
        return (today - pdate.date()).days
    return None


@login_required
def customer_insights(request):
    """GET ?customer=<id> → the 'know your customer' panel payload."""
    customer_id = request.GET.get('customer')
    if not customer_id or not str(customer_id).isdigit():
        return JsonResponse({'ok': False, 'message': 'customer id required'}, status=400)

    customer = Customer.objects.filter(user=request.user, id=int(customer_id)).first()
    if not customer:
        return JsonResponse({'ok': False, 'message': 'customer not found'}, status=404)

    today = date.today()
    book = Book.objects.filter(user=request.user, customer=customer).first()

    balance = float(book.current_balance) if book else 0.0
    # current_balance is NEGATIVE when the customer owes (purchases are stored negative,
    # payments positive). Flip it into a plain "outstanding owed" figure.
    outstanding = round(-balance, 2) if balance < 0 else 0.0
    advance = round(balance, 2) if balance > 0 else 0.0

    if outstanding > 0.01:
        status = 'owes'
        balance_label = f'Owes ₹{outstanding:,.2f}'
    elif advance > 0.01:
        status = 'advance'
        balance_label = f'Advance ₹{advance:,.2f}'
    else:
        status = 'clear'
        balance_label = 'No dues'

    # Aging + last payment come off the active book logs.
    oldest_unpaid_days = None
    last_payment = None
    if book:
        logs = list(BookLog.objects.filter(parent_book=book, is_active=True))
        oldest_unpaid_days = _oldest_unpaid_days(logs, today)

        pay = (BookLog.objects.filter(parent_book=book, is_active=True, change_type=0)
               .order_by('-date', '-id').first())
        if pay:
            last_payment = {
                'amount': round(abs(pay.change), 2),
                'date': pay.date.strftime('%d %b %Y') if pay.date else '',
            }

    # Recent orders for this customer: last order + price history + usual items.
    invoices = list(
        Invoice.objects.filter(user=request.user, invoice_customer=customer)
        .order_by('-invoice_date', '-id')[:40]
    )

    last_order = None
    if invoices:
        latest = invoices[0]
        last_order = {
            'date': latest.invoice_date.strftime('%d %b %Y'),
            'days_ago': (today - latest.invoice_date).days,
            'amount': round(_invoice_total(latest.invoice_json), 2),
            'invoice_number': latest.invoice_number,
        }

    # Walk newest → oldest so the FIRST time we see a model is its most recent price.
    product_last_prices = {}
    usual_counter = {}      # model_no -> {product, count, last_qty}
    for inv in invoices:
        try:
            items = json.loads(inv.invoice_json).get('items', [])
        except (ValueError, TypeError):
            continue
        for item in items:
            model = (item.get('invoice_model_no') or '').strip().upper()
            if not model:
                continue
            if model not in product_last_prices:
                try:
                    product_last_prices[model] = round(float(item.get('invoice_rate_with_gst') or 0), 2)
                except (ValueError, TypeError):
                    pass
            entry = usual_counter.setdefault(model, {
                'model_no': model,
                'product': item.get('invoice_product') or '',
                'count': 0,
                'last_qty': item.get('invoice_qty') or 1,
            })
            entry['count'] += 1

    usual_items = sorted(usual_counter.values(), key=lambda e: e['count'], reverse=True)[:8]

    # Cheque risk: no FK ties a cheque to a customer, so match the payee name (both
    # are stored upper-cased). Heuristic, but the only link available.
    bounced_cheques = ChequeLeaf.objects.filter(
        user=request.user, status='BOUNCED', payee_name=customer.customer_name
    ).count()

    credit_limit = float(customer.credit_limit) if customer.credit_limit is not None else None
    credit_available = round(credit_limit - outstanding, 2) if credit_limit is not None else None

    return JsonResponse({
        'ok': True,
        'customer_id': customer.id,
        'customer_name': customer.customer_name,
        'status': status,
        'balance_label': balance_label,
        'outstanding': outstanding,
        'advance': advance,
        'oldest_unpaid_days': oldest_unpaid_days,
        'last_payment': last_payment,
        'last_order': last_order,
        'bounced_cheques': bounced_cheques,
        'collection_day': customer.get_collection_day_display(),
        'credit_limit': credit_limit,
        'credit_available': credit_available,
        'product_last_prices': product_last_prices,
        'usual_items': usual_items,
    })


@login_required
def today_summary(request):
    """GET → today's sales & collections and this month's GST collected (Group C)."""
    today = date.today()
    month_start = today.replace(day=1)

    todays_invoices = Invoice.objects.filter(user=request.user, invoice_date=today)
    sales_total = 0.0
    for inv_json in todays_invoices.values_list('invoice_json', flat=True):
        sales_total += _invoice_total(inv_json)

    collections_total = 0.0
    todays_payments = BookLog.objects.filter(
        parent_book__user=request.user, is_active=True, change_type=0,
        date__date=today,
    )
    for log in todays_payments:
        collections_total += abs(log.change)

    # GST collected this month = SGST + CGST + IGST across this month's GST invoices.
    gst_month = 0.0
    month_invoices = Invoice.objects.filter(
        user=request.user, is_gst=True, invoice_date__gte=month_start, invoice_date__lte=today,
    )
    for inv_json in month_invoices.values_list('invoice_json', flat=True):
        try:
            data = json.loads(inv_json)
            gst_month += float(data.get('invoice_total_amt_sgst', 0) or 0)
            gst_month += float(data.get('invoice_total_amt_cgst', 0) or 0)
            gst_month += float(data.get('invoice_total_amt_igst', 0) or 0)
        except (ValueError, TypeError):
            continue

    return JsonResponse({
        'ok': True,
        'date': today.strftime('%d %b %Y'),
        'invoice_count': todays_invoices.count(),
        'sales_total': round(sales_total, 2),
        'collections_total': round(collections_total, 2),
        'gst_month': round(gst_month, 2),
        'gst_month_label': today.strftime('%b %Y'),
    })
