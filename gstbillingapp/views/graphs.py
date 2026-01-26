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
    Book, BookLog,
    PurchaseLog, VendorPurchase,
    ExpenseTracker
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
            total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
            total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
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

@login_required
def customer_books_graph(request):
    # Handle AJAX request for data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from datetime import timedelta
        
        # Get transaction types filter (can be multiple)
        transaction_types_param = request.GET.get('transaction_types', '1')
        transaction_types = [int(t) for t in transaction_types_param.split(',') if t]
        
        # Get date range filter
        filter_type = request.GET.get('filter', 'this_month')
        today = datetime.now().date()
        
        if filter_type == 'today':
            start_date = today
            end_date = today
        elif filter_type == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            end_date = today
        elif filter_type == 'this_month':
            start_date = today.replace(day=1)
            end_date = today
        elif filter_type == 'this_year':
            start_date = today.replace(month=1, day=1)
            end_date = today
        elif filter_type == 'all':
            # Get the earliest date from BookLog
            first_log = BookLog.objects.filter(
                parent_book__user=request.user,
                is_active=True
            ).order_by('date').first()
            start_date = first_log.date.date() if first_log else today
            end_date = today
        else:  # custom date range
            start_date = datetime.strptime(request.GET.get('start_date', str(today)), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.GET.get('end_date', str(today)), '%Y-%m-%d').date()
        
        # Fetch data for each selected transaction type
        from collections import defaultdict
        all_data = {}
        
        type_names = {
            0: 'Paid',
            1: 'Purchased Items',
            2: 'Returned Items',
            3: 'Other'
        }
        
        for trans_type in transaction_types:
            logs = BookLog.objects.filter(
                parent_book__user=request.user,
                change_type=trans_type,
                is_active=True,
                date__date__gte=start_date,
                date__date__lte=end_date
            ).order_by('date')
            
            daily_sales = defaultdict(float)
            for log in logs:
                date_str = log.date.strftime('%Y-%m-%d')
                daily_sales[date_str] += abs(log.change)
            
            all_data[trans_type] = {
                'name': type_names.get(trans_type, 'Unknown'),
                'daily': daily_sales
            }
        
        # Prepare data for Google Charts
        chart_data = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            row = {'date': date_str}
            
            for trans_type in transaction_types:
                daily_amount = all_data[trans_type]['daily'].get(date_str, 0)
                row[f'type_{trans_type}'] = round(daily_amount, 2)
            
            chart_data.append(row)
            current_date += timedelta(days=1)
        
        # Calculate totals for each type
        totals = {}
        for trans_type in transaction_types:
            total = sum(all_data[trans_type]['daily'].values())
            totals[trans_type] = round(total, 2)
        
        return JsonResponse({
            'success': True,
            'data': chart_data,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'transaction_types': transaction_types,
            'type_names': {k: v['name'] for k, v in all_data.items()},
            'totals': totals
        })
    
    # Regular page load
    context = {}
    return render(request, "graphs/books_graph.html", context)

@login_required
def customer_graph(request):
    # Handle AJAX request for data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from datetime import timedelta
        from django.db.models import Sum
        
        # Get top N customers
        top_n = int(request.GET.get('top_n', 10))
        sort_by = request.GET.get('sort_by', 'volume')  # 'volume' or 'balance'
        sort_order = request.GET.get('sort_order', 'desc')  # 'desc' or 'asc'
        
        # Get all customers with their books
        customers_data = []
        
        books = Book.objects.filter(
            user=request.user,
            customer__isnull=False
        ).select_related('customer')
        
        for book in books:
            # Calculate total transaction volume (all transaction types)
            total_volume = BookLog.objects.filter(
                parent_book=book,
                change_type__in=[0, 1, 2, 3],  # Paid, Purchased, Returned, Other
                is_active=True
            ).aggregate(total=Sum('change'))['total'] or 0
            
            # Calculate individual transaction type amounts
            type_0 = BookLog.objects.filter(
                parent_book=book, change_type=0, is_active=True
            ).aggregate(total=Sum('change'))['total'] or 0
            
            type_1 = BookLog.objects.filter(
                parent_book=book, change_type=1, is_active=True
            ).aggregate(total=Sum('change'))['total'] or 0
            
            type_2 = BookLog.objects.filter(
                parent_book=book, change_type=2, is_active=True
            ).aggregate(total=Sum('change'))['total'] or 0
            
            type_3 = BookLog.objects.filter(
                parent_book=book, change_type=3, is_active=True
            ).aggregate(total=Sum('change'))['total'] or 0
            
            customers_data.append({
                'name': book.customer.customer_name,
                'volume': abs(total_volume),
                'balance': abs(book.current_balance),
                'type_0': abs(type_0),
                'type_1': abs(type_1),
                'type_2': abs(type_2),
                'type_3': abs(type_3)
            })
        
        # Sort and limit
        reverse_sort = (sort_order == 'desc')
        
        if sort_by == 'balance':
            customers_data.sort(key=lambda x: x['balance'], reverse=reverse_sort)
        elif sort_by == 'type_0':
            customers_data.sort(key=lambda x: x['type_0'], reverse=reverse_sort)
        elif sort_by == 'type_1':
            customers_data.sort(key=lambda x: x['type_1'], reverse=reverse_sort)
        elif sort_by == 'type_2':
            customers_data.sort(key=lambda x: x['type_2'], reverse=reverse_sort)
        elif sort_by == 'type_3':
            customers_data.sort(key=lambda x: x['type_3'], reverse=reverse_sort)
        else:  # volume
            customers_data.sort(key=lambda x: x['volume'], reverse=reverse_sort)
        
        customers_data = customers_data[:top_n]
        
        return JsonResponse({
            'success': True,
            'data': customers_data,
            'sort_by': sort_by,
            'total_customers': len(Book.objects.filter(user=request.user, customer__isnull=False))
        })
    
    # Regular page load
    context = {}
    return render(request, "graphs/customer_graph.html", context)

@login_required
def purchase_log_graph(request):
    # Handle AJAX request for data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from datetime import timedelta
        
        # Get transaction types filter (can be multiple)
        transaction_types_param = request.GET.get('transaction_types', '0')
        transaction_types = [int(t) for t in transaction_types_param.split(',') if t]
        
        # Get date range filter
        filter_type = request.GET.get('filter', 'this_month')
        today = datetime.now().date()
        
        if filter_type == 'today':
            start_date = today
            end_date = today
        elif filter_type == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            end_date = today
        elif filter_type == 'this_month':
            start_date = today.replace(day=1)
            end_date = today
        elif filter_type == 'this_year':
            start_date = today.replace(month=1, day=1)
            end_date = today
        elif filter_type == 'all':
            # Get the earliest date from PurchaseLog
            first_log = PurchaseLog.objects.filter(
                user=request.user
            ).order_by('date').first()
            start_date = first_log.date.date() if first_log else today
            end_date = today
        else:  # custom date range
            start_date = datetime.strptime(request.GET.get('start_date', str(today)), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.GET.get('end_date', str(today)), '%Y-%m-%d').date()
        
        # Fetch data for each selected transaction type
        from collections import defaultdict
        all_data = {}
        
        type_names = {
            0: 'Purchase',
            1: 'Paid',
            3: 'Others'
        }
        
        for trans_type in transaction_types:
            logs = PurchaseLog.objects.filter(
                user=request.user,
                change_type=trans_type,
                date__date__gte=start_date,
                date__date__lte=end_date
            ).order_by('date')
            
            daily_amounts = defaultdict(float)
            for log in logs:
                date_str = log.date.strftime('%Y-%m-%d')
                daily_amounts[date_str] += abs(log.change)
            
            all_data[trans_type] = {
                'name': type_names.get(trans_type, 'Unknown'),
                'daily': daily_amounts
            }
        
        # Prepare data for Google Charts
        chart_data = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            row = {'date': date_str}
            
            for trans_type in transaction_types:
                daily_amount = all_data[trans_type]['daily'].get(date_str, 0)
                row[f'type_{trans_type}'] = round(daily_amount, 2)
            
            chart_data.append(row)
            current_date += timedelta(days=1)
        
        # Calculate totals for each type
        totals = {}
        for trans_type in transaction_types:
            total = sum(all_data[trans_type]['daily'].values())
            totals[trans_type] = round(total, 2)
        
        return JsonResponse({
            'success': True,
            'data': chart_data,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'transaction_types': transaction_types,
            'type_names': {k: v['name'] for k, v in all_data.items()},
            'totals': totals
        })
    
    # Regular page load
    context = {}
    return render(request, "graphs/purchase_log_graph.html", context)

@login_required
def expense_tracker_graph(request):
    # Handle AJAX request for data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from datetime import timedelta
        
        # Get categories filter (can be multiple)
        categories_param = request.GET.get('categories', '')
        selected_categories = [c.strip() for c in categories_param.split(',') if c.strip()]
        
        # Get date range filter
        filter_type = request.GET.get('filter', 'this_month')
        today = datetime.now().date()
        
        if filter_type == 'today':
            start_date = today
            end_date = today
        elif filter_type == 'this_week':
            start_date = today - timedelta(days=today.weekday())
            end_date = today
        elif filter_type == 'this_month':
            start_date = today.replace(day=1)
            end_date = today
        elif filter_type == 'this_year':
            start_date = today.replace(month=1, day=1)
            end_date = today
        elif filter_type == 'all':
            # Get the earliest date from ExpenseTracker
            first_expense = ExpenseTracker.objects.filter(
                user=request.user
            ).order_by('date').first()
            start_date = first_expense.date.date() if first_expense else today
            end_date = today
        else:  # custom date range
            start_date = datetime.strptime(request.GET.get('start_date', str(today)), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.GET.get('end_date', str(today)), '%Y-%m-%d').date()
        
        # If no categories selected, get all categories
        if not selected_categories:
            all_categories = ExpenseTracker.objects.filter(
                user=request.user,
                date__date__gte=start_date,
                date__date__lte=end_date
            ).values_list('category', flat=True).distinct()
            selected_categories = list(all_categories)
        
        # Fetch data for each selected category
        from collections import defaultdict
        all_data = {}
        
        for category in selected_categories:
            expenses = ExpenseTracker.objects.filter(
                user=request.user,
                category=category,
                date__date__gte=start_date,
                date__date__lte=end_date
            ).order_by('date')
            
            daily_amounts = defaultdict(float)
            for expense in expenses:
                date_str = expense.date.strftime('%Y-%m-%d')
                daily_amounts[date_str] += float(expense.amount)
            
            all_data[category] = {
                'name': category,
                'daily': daily_amounts
            }
        
        # Prepare data for Google Charts
        chart_data = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            row = {'date': date_str}
            
            for category in selected_categories:
                daily_amount = all_data[category]['daily'].get(date_str, 0)
                row[f'cat_{category}'] = round(daily_amount, 2)
            
            chart_data.append(row)
            current_date += timedelta(days=1)
        
        # Calculate totals for each category
        totals = {}
        for category in selected_categories:
            total = sum(all_data[category]['daily'].values())
            totals[category] = round(total, 2)
        
        # Get all available categories for the dropdown
        all_available_categories = list(ExpenseTracker.objects.filter(
            user=request.user
        ).values_list('category', flat=True).distinct().order_by('category'))
        
        return JsonResponse({
            'success': True,
            'data': chart_data,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'categories': selected_categories,
            'category_names': {k: v['name'] for k, v in all_data.items()},
            'totals': totals,
            'all_categories': all_available_categories
        })
    
    # Get all categories for initial page load
    all_categories = list(ExpenseTracker.objects.filter(
        user=request.user
    ).values_list('category', flat=True).distinct().order_by('category'))
    
    context = {
        'all_categories': all_categories
    }
    return render(request, "graphs/expense_tracker_graph.html", context)

# ================= Maps =========================================
@login_required
def customer_location_map(request):
    customers = Customer.objects.filter(
        user=request.user,
        customer_latitude__isnull=False,
        customer_longitude__isnull=False
    ).exclude(customer_latitude=None, customer_longitude=None).order_by('customer_name')
    user_profile = UserProfile.objects.get(
        user=request.user,
        business_latitude__isnull=False,
        business_longitude__isnull=False
        )
    all_customers = Customer.objects.filter(user=request.user)
    context = {
        'customers': customers,
        'all_customers': all_customers,
        'user': user_profile,
        'user_profile': user_profile
    }
    return render(request, "graphs/customer_location_map.html", context)