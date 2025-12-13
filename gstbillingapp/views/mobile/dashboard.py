# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
import json

# Models
from ...models import (
    Customer, Employee, UserProfile, Invoice, Product, 
    Inventory, Book, BookLog, PurchaseLog, ReturnInvoice,
    CustomerPayment, CustomerDiscount
)


# ================= Owner Dashboard =============================
@login_required
def owner_dashboard(request):
    """Mobile dashboard for business owner"""
    if request.session.get('user_type') != 'owner':
        return redirect('mobile_login_selection')
    
    user_profile = request.user.userprofile
    today = timezone.now().date()
    month_start = today.replace(day=1)
    
    # Sales metrics - Calculate from JSON
    today_invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date=today
    )
    
    today_sales_total = 0
    for inv in today_invoices:
        try:
            inv_data = json.loads(inv.invoice_json)
            today_sales_total += float(inv_data.get('invoice_total_amt_with_gst', 0))
        except:
            pass
    
    month_invoices = Invoice.objects.filter(
        user=request.user,
        invoice_date__gte=month_start
    )
    
    month_sales_total = 0
    for inv in month_invoices:
        try:
            inv_data = json.loads(inv.invoice_json)
            month_sales_total += float(inv_data.get('invoice_total_amt_with_gst', 0))
        except:
            pass
    
    # Inventory status
    low_stock_count = Inventory.objects.filter(
        user=request.user,
        current_stock__lte=10
    ).count()
    
    # Pending receivables
    pending_receivables = Book.objects.filter(
        user=request.user,
        current_balance__gt=0
    ).aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Recent invoices
    recent_invoices = Invoice.objects.filter(
        user=request.user
    ).order_by('-invoice_date')[:5]
    
    # Employee count
    employee_count = Employee.objects.filter(
        user_profile=user_profile,
        is_active=True
    ).count()
    
    context = {
        'user_profile': user_profile,
        'today_sales': today_sales_total,
        'today_sales_count': today_invoices.count(),
        'month_sales': month_sales_total,
        'month_sales_count': month_invoices.count(),
        'low_stock_count': low_stock_count,
        'pending_receivables': pending_receivables,
        'recent_invoices': recent_invoices,
        'employee_count': employee_count,
    }
    
    return render(request, 'mobile/dashboard/owner_dashboard.html', context)


@login_required
def owner_sales_report(request):
    """Sales report for owner"""
    if request.session.get('user_type') != 'owner':
        return redirect('mobile_login_selection')
    
    # Get date filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    invoices = Invoice.objects.filter(user=request.user).order_by('-invoice_date')
    
    if from_date:
        invoices = invoices.filter(invoice_date__gte=from_date)
    if to_date:
        invoices = invoices.filter(invoice_date__lte=to_date)
    
    # Calculate totals from JSON
    total_amount = 0
    for inv in invoices:
        try:
            inv_data = json.loads(inv.invoice_json)
            total_amount += float(inv_data.get('invoice_total_amt_with_gst', 0))
        except:
            pass
    
    totals = {
        'total_amount': total_amount,
        'total_count': invoices.count()
    }
    
    context = {
        'invoices': invoices[:50],  # Limit for mobile
        'totals': totals,
        'from_date': from_date,
        'to_date': to_date,
    }
    
    return render(request, 'mobile/dashboard/owner_sales_report.html', context)


@login_required
def owner_inventory_status(request):
    """Inventory status for owner"""
    if request.session.get('user_type') != 'owner':
        return redirect('mobile_login_selection')
    
    inventory_items = Inventory.objects.filter(
        user=request.user
    ).select_related('product').order_by('current_stock')
    
    # Filter by stock status
    stock_filter = request.GET.get('filter', 'all')
    if stock_filter == 'low':
        inventory_items = inventory_items.filter(current_stock__lte=10)
    elif stock_filter == 'out':
        inventory_items = inventory_items.filter(current_stock=0)
    
    context = {
        'inventory_items': inventory_items[:100],
        'stock_filter': stock_filter,
    }
    
    return render(request, 'mobile/dashboard/owner_inventory.html', context)


# ================= Employee Dashboard =============================
@login_required
def employee_dashboard(request):
    """Mobile dashboard for employees"""
    if request.session.get('user_type') != 'employee':
        return redirect('mobile_login_selection')
    
    employee_id = request.session.get('employee_id')
    employee = get_object_or_404(Employee, id=employee_id)
    
    today = timezone.now().date()
    
    # Employee's sales today (if they create invoices)
    if employee.can_create_invoice:
        today_invoices = Invoice.objects.filter(
            user=request.user,
            invoice_date=today
        )
        
        today_sales_total = 0
        for inv in today_invoices:
            try:
                inv_data = json.loads(inv.invoice_json)
                today_sales_total += float(inv_data.get('invoice_total_amt_with_gst', 0))
            except:
                pass
        
        today_sales = {'total': today_sales_total, 'count': today_invoices.count()}
    else:
        today_sales = {'total': 0, 'count': 0}
    
    # Recent activities
    recent_invoices = Invoice.objects.filter(
        user=request.user
    ).order_by('-invoice_date')[:5]
    
    # Low stock alerts (if inventory manager)
    low_stock_count = 0
    if employee.can_manage_inventory:
        low_stock_count = Inventory.objects.filter(
            user=request.user,
            current_stock__lte=10
        ).count()
    
    context = {
        'employee': employee,
        'today_sales': today_sales['total'] or 0,
        'today_sales_count': today_sales['count'],
        'recent_invoices': recent_invoices,
        'low_stock_count': low_stock_count,
    }
    
    return render(request, 'mobile/dashboard/employee_dashboard.html', context)


@login_required
def employee_create_invoice(request):
    """Quick invoice creation for employees"""
    if request.session.get('user_type') != 'employee':
        return redirect('mobile_login_selection')
    
    employee_id = request.session.get('employee_id')
    employee = get_object_or_404(Employee, id=employee_id)
    
    if not employee.can_create_invoice:
        return JsonResponse({'error': 'No permission to create invoices'}, status=403)
    
    # Redirect to main invoice creation (they can use the full interface)
    return redirect('invoice_create')


# ================= Customer Dashboard =============================
@login_required
def customer_dashboard(request):
    """Mobile dashboard for customers"""
    if request.session.get('user_type') != 'customer':
        return redirect('mobile_login_selection')
    
    customer_id = request.session.get('customer_id')
    customer = get_object_or_404(Customer, id=customer_id)
    
    # Get customer's book (ledger)
    try:
        book = Book.objects.get(customer=customer)
        current_balance = book.current_balance
    except Book.DoesNotExist:
        current_balance = 0
    
    # Recent invoices
    recent_invoices_raw = Invoice.objects.filter(
        invoice_customer=customer
    ).order_by('-invoice_date')[:10]
    
    # Parse JSON for each recent invoice
    recent_invoices = []
    for invoice in recent_invoices_raw:
        invoice_dict = {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.invoice_date,
            'non_gst_invoice_number': invoice.non_gst_invoice_number,
            'invoice_customer': invoice.invoice_customer,
        }
        try:
            invoice_dict['data'] = json.loads(invoice.invoice_json)
        except:
            invoice_dict['data'] = None
        recent_invoices.append(invoice_dict)
    
    # Recent payments
    recent_payments = CustomerPayment.objects.filter(
        customer=customer
    ).order_by('-payment_date')[:5]
    
    # Recent returns
    recent_returns = ReturnInvoice.objects.filter(
        customer=customer
    ).order_by('-created_at')[:5]
    
    # Calculate totals from invoices
    all_invoices = Invoice.objects.filter(invoice_customer=customer)
    total_purchases = 0
    for inv in all_invoices:
        try:
            inv_data = json.loads(inv.invoice_json)
            total_purchases += float(inv_data.get('invoice_total_amt_with_gst', 0))
        except:
            pass
    
    total_payments = CustomerPayment.objects.filter(
        customer=customer
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    context = {
        'customer': customer,
        'current_balance': current_balance,
        'recent_invoices': recent_invoices,
        'recent_payments': recent_payments,
        'recent_returns': recent_returns,
        'total_purchases': total_purchases,
        'total_payments': total_payments,
    }
    
    return render(request, 'mobile/dashboard/customer_dashboard.html', context)


@login_required
def customer_invoices(request):
    """View all customer invoices"""
    if request.session.get('user_type') != 'customer':
        return redirect('mobile_login_selection')
    
    customer_id = request.session.get('customer_id')
    customer = get_object_or_404(Customer, id=customer_id)
    
    invoices = Invoice.objects.filter(
        invoice_customer=customer
    ).order_by('-invoice_date')
    
    # Parse JSON for each invoice
    invoices_with_data = []
    for invoice in invoices:
        invoice_dict = {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'invoice_date': invoice.invoice_date,
            'non_gst_invoice_number': invoice.non_gst_invoice_number,
        }
        try:
            invoice_dict['data'] = json.loads(invoice.invoice_json)
        except:
            invoice_dict['data'] = None
        invoices_with_data.append(invoice_dict)
    
    context = {
        'customer': customer,
        'invoices': invoices_with_data,
    }
    
    return render(request, 'mobile/dashboard/customer_invoices.html', context)


@login_required
def customer_invoice_detail(request, invoice_id):
    """View specific invoice details"""
    if request.session.get('user_type') != 'customer':
        return redirect('mobile_login_selection')
    
    customer_id = request.session.get('customer_id')
    customer = get_object_or_404(Customer, id=customer_id)
    
    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_customer=customer)
    
    # Parse invoice JSON
    try:
        invoice_data = json.loads(invoice.invoice_json)
    except:
        invoice_data = None
    
    context = {
        'customer': customer,
        'invoice': invoice,
        'invoice_data': invoice_data,
    }
    
    return render(request, 'mobile/dashboard/customer_invoice_detail.html', context)


@login_required
def customer_ledger(request):
    """View customer ledger/statement"""
    if request.session.get('user_type') != 'customer':
        return redirect('mobile_login_selection')
    
    customer_id = request.session.get('customer_id')
    customer = get_object_or_404(Customer, id=customer_id)
    
    try:
        book = Book.objects.get(customer=customer)
        book_logs = BookLog.objects.filter(book=book).order_by('-date')[:50]
    except Book.DoesNotExist:
        book = None
        book_logs = []
    
    context = {
        'customer': customer,
        'book': book,
        'book_logs': book_logs,
    }
    
    return render(request, 'mobile/dashboard/customer_ledger.html', context)
