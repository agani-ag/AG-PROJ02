# Django imports
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse

# Models
from ..models import Customer, UserProfile, Invoice

# Python imports
from datetime import date, timedelta
import json
import calendar

@login_required
def sales_report(request):
    context = {}
    user = request.user

    # User profile
    context['user_profile'] = UserProfile.objects.get(user=user)

    # Customers
    context['customers'] = Customer.objects.filter(user=user).order_by('customer_name')

    # Month names
    context['months'] = [(i, calendar.month_name[i]) for i in range(1, 13)]
    context['current_month'] = date.today().month

    # Year list (last 5 years)
    current_year = date.today().year
    context['year_list'] = [current_year - i for i in range(5)]
    context['current_year'] = current_year

    # Get filters from GET
    month = int(request.GET.get('month', context['current_month']))
    year = int(request.GET.get('year', context['current_year']))
    customer_id = request.GET.get('customer')

    # Calculate first and last day of the month
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)

    # Filter invoices
    invoices = Invoice.objects.filter(
        user=user,
        invoice_date__range=(first_day, last_day)
    )

    if customer_id:
        invoices = invoices.filter(invoice_customer_id=customer_id)

    # Aggregate sales per customer
    customer_sales = []
    selected_customers = Customer.objects.filter(user=user).order_by('customer_name')
    if customer_id:
        selected_customers = selected_customers.filter(id=customer_id)

    for customer in selected_customers:
        customer_invoices = invoices.filter(invoice_customer=customer)
        total_invoices = customer_invoices.count()
        total_amount = 0
        for invoice in customer_invoices:
            try:
                data = json.loads(invoice.invoice_json)
                total_amount += float(data.get('invoice_total_amt_with_gst', 0))
            except Exception:
                pass
        customer_sales.append({
            'customer': str(customer),
            'total_invoices': total_invoices,
            'total_amount': total_amount,
        })

    # Return JSON if AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'customer_sales': customer_sales})

    context['customer_sales'] = customer_sales
    return render(request, "reports/sales_report.html", context)
