# Django imports
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    PurchaseLog, VendorPurchase
)

# Forms
from ..forms import (
    PurchaseLogForm
)
# Third-party libraries
import json
import datetime

# ================= Purchases =============================
@login_required
def purchases_logs(request):
    context = {}
    context['total_purchased'] = PurchaseLog.objects.filter(user=request.user, change_type=0).aggregate(Sum('change'))['change__sum']
    context['total_paid'] = PurchaseLog.objects.filter(user=request.user, change_type=1).aggregate(Sum('change'))['change__sum']
    context['total_others'] = PurchaseLog.objects.filter(user=request.user, change_type=3).aggregate(Sum('change'))['change__sum']
    context['total_balance'] = PurchaseLog.objects.filter(user=request.user).aggregate(Sum('change'))['change__sum']
    
    context['purchases'] = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    return render(request, 'purchases/purchases.html', context)

@login_required
def purchases_logs_add(request):
    context = {}
    context['categories'] = PurchaseLog.objects.filter(user=request.user).values_list('category', flat=True).distinct().exclude(category__isnull=True)
    context['references'] = PurchaseLog.objects.filter(user=request.user).values_list('reference', flat=True).distinct().exclude(reference__isnull=True)
    context['form'] = PurchaseLogForm()
        
    if request.method == "POST":
        form = PurchaseLogForm(request.POST)
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.user = request.user
            purchase.change = get_change_type_change(request.POST.get('change_type'), request.POST.get('change'))
            # purchase.vendor = get_vendor_instance(request.POST.get('vendor'), request)
            purchase.save()
            return redirect('purchases_logs')
    return render(request,'purchases/purchase_add.html',context)

@login_required
def purchases_logs_delete(request,pid):
    if pid:
        purchases_obj = get_object_or_404(PurchaseLog, user=request.user, id=pid)
        purchases_obj.delete()
    return redirect('purchases_logs')

# ================= Utilities ====================================
def get_change_type_change(change_type, change):
    if change_type == '0':
        if int(change) > 0:
            change = -int(change)
    else:
        change = abs(int(change))
    return change

def get_vendor_instance(vendor, request):
    if vendor == '':
        vendor_instance = None
    else:
        vendor_instance = VendorPurchase.objects.get(user=request.user, id=vendor)
    return vendor_instance