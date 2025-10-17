# Django imports
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import Invoice
from ..models import Product
from ..models import Inventory
from ..models import InventoryLog

# Forms
from ..forms import InventoryLogForm


# ================= Inventory Views ===========================
@login_required
def inventory(request):
    context = {}
    context['inventory_list'] = Inventory.objects.filter(user=request.user).exclude(product_id__isnull=True)
    context['untracked_products'] = Product.objects.filter(user=request.user, inventory=None).exclude(model_no__isnull=True)
    return render(request, 'inventory/inventory.html', context)

@login_required
def inventory_logs(request, inventory_id):
    context = {}
    inventory = get_object_or_404(Inventory, id=inventory_id, user=request.user)
    inventory_logs = InventoryLog.objects.filter(user=request.user, product=inventory.product).order_by('-id')
    context['inventory'] = inventory
    context['inventory_logs'] = inventory_logs
    return render(request, 'inventory/inventory_logs.html', context)


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