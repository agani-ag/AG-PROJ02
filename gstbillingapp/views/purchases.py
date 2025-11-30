# Django imports
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import UserProfile
from ..models import PurchaseLog
from ..models import VendorPurchase

# Third-party libraries
import json
import datetime

# ================= Purchases =============================
@login_required
def purchases(request):
    context = {}
    # context['purchases'] = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    context['total_p'] = PurchaseLog.objects.filter(user=request.user, ptype=0).aggregate(Sum('amount'))['amount__sum']
    context['total_pp'] = PurchaseLog.objects.filter(user=request.user, ptype=1).aggregate(Sum('amount'))['amount__sum']
    context['total_pb'] = PurchaseLog.objects.filter(user=request.user).aggregate(Sum('amount'))['amount__sum']
    
    context['purchases'] = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    return render(request, 'purchases/purchases.html', context)

@login_required
def purchases_add(request):
    context = {}
    context['vendors'] = VendorPurchase.objects.filter(user=request.user)
    context['paid_categories'] = PurchaseLog.objects.filter(user=request.user).values_list('paid_category', flat=True).distinct()
    context['purchase_categories'] = PurchaseLog.objects.filter(user=request.user).values_list('purchase_category', flat=True).distinct()
    if request.method == 'POST':
        date = request.POST.get('date')
        ptype = request.POST.get('ptype')
        paid_reference = request.POST.get('paid_reference')
        purchase_reference = request.POST.get('purchase_reference')
        amount = request.POST.get('amount')
        status = request.POST.get('status')
        vendor = request.POST.get('vendor')
        paid_category = request.POST.get('paid_category')
        purchase_category = request.POST.get('purchase_category')
        
        purchase = PurchaseLog(
            user = request.user,
            date = date,
            ptype = int(ptype),
            status = status,
            paid_category = paid_category,
            paid_reference = paid_reference,
            purchase_category = purchase_category,
            purchase_reference = purchase_reference,
            amount = get_ptype_amount(ptype, amount),
            vendor = get_vendor_instance(vendor, request),
        )
        purchase.save()
        return redirect('purchases')
    return render(request,'purchases/purchase_add.html',context)

@login_required
def purchases_edit(request,pid):
    context = {}
    purchase_log = get_object_or_404(PurchaseLog, user=request.user, id=pid)
    context['purchase_log'] = purchase_log
    context['vendors'] = VendorPurchase.objects.filter(user=request.user)
    context['paid_categories'] = PurchaseLog.objects.filter(user=request.user).values_list('paid_category', flat=True).distinct()
    context['purchase_categories'] = PurchaseLog.objects.filter(user=request.user).values_list('purchase_category', flat=True).distinct()
    if request.method == 'POST':
        ptype = request.POST.get('ptype')
        amount = request.POST.get('amount')
        vendor = request.POST.get('vendor')
        
        purchase_log.ptype = int(ptype)
        purchase_log.date = request.POST.get('date')
        purchase_log.status = request.POST.get('status')
        purchase_log.amount = get_ptype_amount(ptype, amount)
        purchase_log.vendor = get_vendor_instance(vendor, request)
        purchase_log.paid_category = request.POST.get('paid_category')
        purchase_log.paid_reference = request.POST.get('paid_reference')
        purchase_log.purchase_category = request.POST.get('purchase_category')
        purchase_log.purchase_reference = request.POST.get('purchase_reference')
        
        purchase_log.save()
        return redirect('purchases')
    return render(request,'purchases/purchase_edit.html',context)

@login_required
def purchases_delete(request,pid):
    if pid:
        purchases_obj = get_object_or_404(PurchaseLog, user=request.user, id=pid)
        purchases_obj.delete()
    return redirect('purchases')

# ================= Utilities ====================================
def get_ptype_amount(ptype, amount):
    if ptype == '0':
        if int(amount) > 0:
            amount = -int(amount)
    else:
        amount = abs(int(amount))
    return amount

def get_vendor_instance(vendor, request):
    if vendor == '':
        vendor_instance = None
    else:
        vendor_instance = VendorPurchase.objects.get(user=request.user, id=vendor)
    return vendor_instance