# Django imports
import csv
from django.db.models import Sum
from django.db.models import Sum, Q
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.db.models.functions import TruncMonth
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    Invoice, UserProfile,
    Product, Inventory, InventoryLog,
)

# Forms
from ..forms import InventoryLogForm

# Utility functions
from gstbillingapp.utils import add_stock_to_inventory

# Python imports
import json
from datetime import date, datetime

# ================= Inventory Views ===========================
def _filtered_inventory(request):
    qs = (Inventory.objects.filter(user=request.user)
          .exclude(product_id__isnull=True).select_related('product').order_by('-product__id'))
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(product__model_no__icontains=q) | Q(product__product_name__icontains=q))
    return qs, q


@login_required
def inventory(request):
    qs, q = _filtered_inventory(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'inventory/inventory.html', {
        'inventory_list': page_obj, 'page_obj': page_obj, 'total_count': paginator.count,
        'q': q, 'querystring': params.urlencode(),
        'untracked_products': Product.objects.filter(user=request.user, inventory=None).exclude(model_no__isnull=True),
    })


@login_required
def inventory_export(request):
    qs, _q = _filtered_inventory(request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory.csv"'
    writer = csv.writer(response)
    writer.writerow(['Model No', 'Product Name', 'Current Stock', 'Alert Level'])
    for inv in qs:
        writer.writerow([inv.product.model_no, inv.product.product_name or '', inv.current_stock, inv.alert_level])
    return response

@login_required
def inventory_logs(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = InventoryLog.objects.filter(user=request.user, product=inventory.product).order_by('-id')
    price = inventory.product.product_rate_with_gst if inventory.product.product_rate_with_gst else 0
    discount = inventory.product.product_discount if inventory.product.product_discount else 0
    gst = inventory.product.product_gst_percentage if inventory.product.product_gst_percentage else 0
    sales_price = price * (1 - discount / 100) * (1 + gst / 100)
    context['sales_price'] = sales_price
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    context['nav_hide'] = request.GET.get('nav') or ''
    return render(request, 'inventory/inventory_logs.html', context)

def _filtered_inventory_logs_full(request):
    """Shared date-range filter for the Inventory Logs list + its CSV export.
    Returns (queryset, filter_context). Server-paginated natively (no DataTables)."""
    from datetime import timedelta
    qs = InventoryLog.objects.filter(user=request.user).select_related('product')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    # Default to the current month (matches the old client-side default).
    if not from_date and not to_date:
        today = datetime.now().date()
        from_date = today.replace(day=1).isoformat()
        if today.month == 12:
            nextm = today.replace(year=today.year + 1, month=1, day=1)
        else:
            nextm = today.replace(month=today.month + 1, day=1)
        to_date = (nextm - timedelta(days=1)).isoformat()
    if from_date and to_date:
        qs = qs.filter(date__date__range=[from_date, to_date])
    qs = qs.order_by('-date')
    return qs, {
        'from_date': from_date, 'to_date': to_date,
        'year': request.GET.get('year', ''), 'month': request.GET.get('month', ''),
        'top_n': request.GET.get('top_n', '5'),
    }


@login_required
def inventory_logs_full(request):
    qs, fctx = _filtered_inventory_logs_full(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    context = dict(fctx)
    context['page_obj'] = page_obj
    context['total_count'] = paginator.count
    context['querystring'] = params.urlencode()
    context['years'] = list(range(2020, datetime.now().year + 1))
    return render(request, 'inventory/inventory_logs_full.html', context)


@login_required
def inventory_logs_full_export(request):
    """Server-side CSV export of the current Inventory Logs filter (all rows)."""
    qs, _ = _filtered_inventory_logs_full(request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory-logs.csv"'
    writer = csv.writer(response)
    writer.writerow(['Date', 'Type', 'Change', 'Description', 'Product'])
    for o in qs:
        writer.writerow([
            o.date.strftime('%b %d %Y') if o.date else '',
            o.get_change_type_display(),
            o.change,
            o.description or '',
            str(o.product),
        ])
    return response

@login_required
def inventory_logs_add(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = Inventory.objects.filter(user=request.user, product=inventory.product)
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    context['form'] = InventoryLogForm()

    if request.method == "POST":
        inventory_log_form = InventoryLogForm(request.POST)
        invoice_no = request.POST["invoice_no"]
        invoice = None
        if invoice_no:
            try:
                invoice_no = int(invoice_no)
                invoice = Invoice.objects.get(user=request.user, invoice_number=invoice_no)
            except:
                context['error_message'] = "Incorrect invoice number %s"%(invoice_no,)
                return render(request, 'inventory/inventory_logs_add.html', context)
                context['form'] = inventory_log_form
                return render(request, 'inventory/inventory_logs_add.html', context)

        inventory_log = inventory_log_form.save(commit=False)
        inventory_log.user = request.user
        inventory_log.product = inventory.product
        if invoice:
            inventory_log.associated_invoice = invoice
        inventory_log.save()
        inventory.current_stock = inventory.current_stock + inventory_log.change
        inventory.last_log = inventory_log
        inventory.save()
        return redirect('inventory_logs', inventory.id)
    return render(request, 'inventory/inventory_logs_add.html', context)

@login_required
def inventory_logs_del(request, inventorylog_id):
    invlg = get_object_or_404(InventoryLog, id=inventorylog_id)
    inv_obj = get_object_or_404(Inventory, id=invlg.product.id, user=request.user)
    invlg.delete()
    new_total = InventoryLog.objects.filter(product=inv_obj.product).aggregate(Sum('change'))['change__sum']
    new_last_log = InventoryLog.objects.filter(product=inv_obj.product).last()
    if not new_total:
        new_total = 0
    inv_obj.current_stock = new_total
    inv_obj.last_log = new_last_log
    inv_obj.save()
    return redirect('inventory_logs', inv_obj.id)

# ================= Inventory API Views ===========================
@csrf_exempt
def invertory_stock_alert_update(request):
    if request.method == "POST":
        inventory_id = request.POST["inventory_id"]
        alert_level = request.POST["alert_level"]
        inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
        inventory.alert_level = int(alert_level)
        inventory.save()
        return JsonResponse({'status': 'success', 'message': f'Product Alert Stock {alert_level} set successfully.'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add products alert stock.'})

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.core.cache import cache
from datetime import date

@login_required
def inventory_logs_ajax(request):
    start = int(request.GET.get('start',0))
    length = int(request.GET.get('length',25))
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    qs = InventoryLog.objects.filter(user=request.user)

    if from_date and to_date:
        qs = qs.filter(date__date__range=[from_date,to_date])

    total = qs.count()
    qs = qs.order_by('-date')[start:start+length]

    data = [[
        o.date.strftime('%b %d %Y'),
        o.get_change_type_display(),
        o.change,
        o.description,
        str(o.product)
    ] for o in qs]

    return JsonResponse({
        'recordsTotal': total,
        'recordsFiltered': total,
        'data': data,
        'draw': int(request.GET.get('draw',1))
    })

@login_required
def inventory_trend_chart(request):
    year = request.GET.get('year')
    if not year:
        year = date.today().year
    else:
        try:
            year = int(year)
        except ValueError:
            year = date.today().year

    cache_key = f"trend_{request.user.id}_{year}"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached, safe=False)

    # Filter logs by year
    qs = InventoryLog.objects.filter(
        user=request.user,
        date__year=year
    ).annotate(month=TruncMonth('date'))

    # Aggregate stock_in and stock_out separately
    monthly_data = qs.values('month').annotate(
        stock_in=Sum('change', filter=Q(change__gt=0)),   # positive changes
        stock_out=Sum('change', filter=Q(change__lt=0))   # negative changes
    ).order_by('month')

    # Prepare chart data for Google Charts
    data = [['Month', 'Stock In', 'Stock Out']]
    for q in monthly_data:
        month_label = q['month'].strftime('%b')
        stock_in = float(q['stock_in'] or 0)
        stock_out = abs(float(q['stock_out'] or 0))  # convert negative to positive for chart
        data.append([month_label, stock_in, stock_out])

    cache.set(cache_key, data, 600)  # cache 10 minutes
    return JsonResponse(data, safe=False)


@login_required
def inventory_product_chart(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    qs = InventoryLog.objects.filter(user=request.user)
    if from_date and to_date:
        qs = qs.filter(date__date__range=[from_date, to_date])

    # Sum stock change per product
    qs = qs.values('product__product_name').annotate(
        total_in=Sum('change', filter=Q(change_type__in=[1,2,3])),   # Stock In
        total_out=Sum('change', filter=Q(change_type=4))              # Stock Out
    )

    # Compute net change for chart
    chart_data = [['Product', 'Net Change']]
    for q in qs:
        product = q['product__product_name'] or 'Unknown'
        net = float((q['total_in'] or 0) - (q['total_out'] or 0))
        chart_data.append([product, net])

    # Sort by absolute change and take top 10
    chart_data = [chart_data[0]] + sorted(chart_data[1:], key=lambda x: abs(x[1]), reverse=True)[:10]

    return JsonResponse(chart_data, safe=False)