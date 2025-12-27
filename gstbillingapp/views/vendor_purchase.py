# Django imports
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import VendorPurchase

# Forms
from ..forms import VendorPurchaseForm

# ================= Vendor Purchase Views ==============================
@login_required
def vendors_purchase(request):
    context = {}
    context['vendors'] = VendorPurchase.objects.filter(user=request.user)
    return render(request, 'vendor_purchase/vendors_purchase.html', context)


@login_required
def vendor_purchase_edit(request, vendor_purchase_id):
    vendor_purchase_obj = get_object_or_404(VendorPurchase, user=request.user, id=vendor_purchase_id)
    if request.method == "POST":
        vendor_purchase_form = VendorPurchaseForm(request.POST, instance=vendor_purchase_obj)
        if vendor_purchase_form.is_valid():
            new_vendor_purchase = vendor_purchase_form.save()
            return redirect('vendors_purchase')
    context = {}
    context['vendor_purchase_form'] = VendorPurchaseForm(instance=vendor_purchase_obj)
    context['id'] = vendor_purchase_obj.id
    return render(request, 'vendor_purchase/vendor_purchase_edit.html', context)


@login_required
def vendor_purchase_add(request):
    if request.method == "POST":
        vendor_purchase_form = VendorPurchaseForm(request.POST)
        if vendor_purchase_form.is_valid():
            new_vendor_purchase = vendor_purchase_form.save(commit=False)
            new_vendor_purchase.user = request.user
            new_vendor_purchase.save()

            return redirect('vendors_purchase')
    context = {}
    context['vendor_purchase_form'] = VendorPurchaseForm()
    return render(request, 'vendor_purchase/vendor_purchase_edit.html', context)


@login_required
def vendor_purchase_delete(request):
    if request.method == "POST":
        vendor_purchase_id = request.POST["vendor_purchase_id"]
        vendor_purchase_obj = get_object_or_404(VendorPurchase, user=request.user, id=vendor_purchase_id)
        vendor_purchase_obj.delete()
    return redirect('vendors_purchase')

# ================= API ====================================
@login_required
def vendorPurchaseFilter(request):
    vendors = VendorPurchase.objects.filter(user=request.user).order_by('vendor_name')

    data = []
    for vendor in vendors:
        data.append({
            "id": vendor.id,
            "name": vendor.vendor_name,
            "address": vendor.vendor_address,
            "phone": vendor.vendor_phone,
            "gstin": vendor.vendor_gst
        })

    return JsonResponse(data, safe=False)