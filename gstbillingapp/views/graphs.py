# Django imports
from gstbilling import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, FloatField, Min, Max
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.hashers import make_password, check_password
# Models
from ..models import (
    Customer, UserProfile,
    Book, BookLog
)

# Other imports
from datetime import datetime

# ================= Graphs Views ===========================
@login_required
def sales_dashboard(request):
    # Get available years from BookLog for the current user
    year_queryset = BookLog.objects.filter(
        parent_book__user=request.user
    ).annotate(year=ExtractYear('date')).values_list('year', flat=True).distinct().order_by('year')

    years = list(year_queryset)[::-1]

    if not years:
        years = [datetime.now().year]

    # Selected financial year
    selected_year = int(request.GET.get('year', years[-1]))

    chart_data = []

    # Financial year: April to March
    for month_offset in range(12):
        month = (month_offset + 4) % 12 or 12
        year = selected_year if month >= 4 else selected_year + 1

        month_logs = BookLog.objects.filter(
            parent_book__user=request.user,
            date__year=year,
            date__month=month
        )

        # Sales: positive change
        sales = month_logs.filter(change__lt=0).aggregate(total=Sum('change'))['total'] or 0
        sales = abs(sales)  # convert to positive

        # Received: negative change
        received_total = month_logs.filter(change__gt=0).aggregate(total=Sum('change'))['total'] or 0
        received = abs(received_total)  # convert to positive

        # Expenses (placeholder)
        expenses = 0

        # Profit = Sales − Received
        # profit = sales - received
        profit = received - sales

        chart_data.append({
            'month': f'{month:02d}-{year}',
            'sales': sales,
            'received': received,
            'expenses': expenses,
            'profit': profit
        })

    context = {
        'years': years,
        'selected_year': selected_year,
        'chart_data': chart_data
    }

    return render(request, "graphs/sales_dashboard.html", context)
