# Django imports
from django.db.models import Sum
from django.http import JsonResponse
from django.core.paginator import Paginator
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


# ================= Inventory Views ===========================
@login_required
def inventory(request):
    context = {}
    context['inventory_list'] = Inventory.objects.filter(user=request.user).exclude(product_id__isnull=True).order_by('-product__id')
    context['untracked_products'] = Product.objects.filter(user=request.user, inventory=None).exclude(model_no__isnull=True)
    return render(request, 'inventory/inventory.html', context)

@login_required
def inventory_logs(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = InventoryLog.objects.filter(user=request.user, product=inventory.product).order_by('-id')
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    context['nav_hide'] = request.GET.get('nav') or ''
    return render(request, 'inventory/inventory_logs.html', context)

@login_required
def inventory_logs_full(request):
    context = {}
    inventory_logs = InventoryLog.objects.filter(user=request.user).order_by('-id')
    context['inventory_logs'] = inventory_logs
    return render(request, 'inventory/inventory_logs_full.html', context)

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
def inventory_api_stock_add(request):
    if request.method == "POST":
        business_uid = request.GET.get('business_uid', None)
        notes = request.GET.get('notes', 'API Stock')
        if not business_uid:
            return JsonResponse({'status': 'error', 'message': 'Business UID is required.'})
        user_profile = get_object_or_404(UserProfile, business_uid=business_uid)
        if user_profile:
            user = user_profile.user
        data = request.body.decode('utf-8')
        data = json.loads(data)
        inserted_count = 0
        not_inserted_count = 0
        increased_quantity = 0
        decreased_quantity = 0
        for item in data:
            if item.get('model_no') == "" or item.get('model_no') is None:
                not_inserted_count += 1
            elif Product.objects.filter(user=user, model_no=item.get('model_no').upper()).exists():
                product = Product.objects.get(user=user, model_no=item.get('model_no').upper())
                product_stock = item.get('product_stock') or 0
                if int(product_stock) > 0:
                    add_stock_to_inventory(product, int(product_stock), notes, user)
                    inserted_count += 1
                    increased_quantity += int(product_stock)
                elif int(product_stock) < 0:
                    add_stock_to_inventory(product, -abs(int(product_stock)), notes, user)
                    inserted_count += 1
                    decreased_quantity += -abs(int(product_stock))
                else:
                    not_inserted_count += 1
        return JsonResponse({'status': 'success', 'message': f'{inserted_count} Products Stock added successfully.\n{not_inserted_count} Products Stock not added.\nQuantity Added: {increased_quantity}\nQuantity Removed: {decreased_quantity}'})
    return JsonResponse({'status': 'error', 'message': 'Use POST method to add products stock.'})

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

    # ✅ FIX: fallback if empty or invalid
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = date.today().year

    cache_key = f"trend_{request.user.id}_{year}"

    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached, safe=False)

    qs = (
        InventoryLog.objects
        .filter(user=request.user, date__year=year)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('change'))
        .order_by('month')
    )

    data = [['Month', 'Change']]
    for q in qs:
        if q['month']:  # safety
            data.append([q['month'].strftime('%b'), float(q['total'])])

    cache.set(cache_key, data, 600)
    return JsonResponse(data, safe=False)


@login_required
def inventory_product_chart(request):
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    qs = InventoryLog.objects.filter(user=request.user)

    if from_date and to_date:
        qs = qs.filter(date__date__range=[from_date, to_date])

    qs = (
        qs.values('product__product_name')  # ✅ FIX HERE
        .annotate(total=Sum('change'))
        .order_by('-total')[:10]
    )

    data = [['Product', 'Change']]
    for q in qs:
        name = q['product__product_name'] or 'UNKNOWN'
        data.append([name, float(q['total'])])

    return JsonResponse(data, safe=False)
