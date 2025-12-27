# Django imports
from gstbilling import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Case, When, FloatField, F
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
    selected_year = int(request.GET.get('year', max(years)))

    chart_data = []

    # Financial year: April to March
    for month_offset in range(12):
        month = (month_offset + 4) % 12 or 12
        year = selected_year if month >= 4 else selected_year + 1

        month_logs = BookLog.objects.filter(
            parent_book__isnull=False,
            parent_book__user=request.user,
            date__year=year,
            date__month=month,
            is_active=True
        )

        totals = month_logs.aggregate(
            total_purchased=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
            total_paid=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
            total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
            total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
        )

        chart_data.append({
            'month': f'{month:02d}-{year}',
            'sales': abs(totals['total_purchased'] or 0),
            'received': abs(totals['total_paid'] or 0),
            'returned': abs(totals['total_returned'] or 0),
            'others': abs(totals['total_others'] or 0),
        })

    context = {
        'years': years,
        'selected_year': selected_year,
        'chart_data': chart_data
    }

    return render(request, "graphs/sales_dashboard.html", context)
