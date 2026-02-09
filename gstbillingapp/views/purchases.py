# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Case, When, FloatField, F, Q

# Models
from ..models import (
    PurchaseLog, VendorPurchase
)

# Forms
from ..forms import (
    PurchaseLogForm
)
# Third-party libraries
import num2words
import json
import datetime

# ================= Purchases =============================
@login_required
def purchases_logs(request):
    context = {}
    purchases_logs = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    totals = purchases_logs.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )
    # Fill in context with totals, using 0 if None
    total_purchased = totals['total_purchased'] or 0
    total_paid = totals['total_paid'] or 0
    total_returned = totals['total_returned'] or 0
    total_others = totals['total_others'] or 0
    total_balance = abs(total_purchased) - (abs(total_paid) + abs(total_returned) + abs(total_others))
    # Calculate balance (absolute value if you want it always positive)
    context['total_balance'] = total_balance
    context['total_balance_word'] = num2words.num2words(abs(int(context['total_balance'])), lang='en_IN').title()
    context['total_purchased'] = abs(total_purchased)
    context['total_paid'] = abs(total_paid)
    context['total_returned'] = abs(total_returned)
    context['total_others'] = abs(total_others)
    if request.GET.get('filter') == 'paid':
        purchases_logs = purchases_logs.filter(change_type=0)
    elif request.GET.get('filter') == 'purchased':
        purchases_logs = purchases_logs.filter(change_type=1)
    elif request.GET.get('filter') == 'returned':
        purchases_logs = purchases_logs.filter(change_type=2)
    elif request.GET.get('filter') == 'others':
        purchases_logs = purchases_logs.filter(change_type=3)
    else:
        purchases_logs = purchases_logs.filter(Q(change_type=0) | Q(change_type=1) | Q(change_type=2) | Q(change_type=3))
    context['purchases'] = purchases_logs    
    return render(request, 'purchases/purchases.html', context)

@login_required
def purchases_logs_add(request):
    context = {}
    context['categories'] = PurchaseLog.objects.filter(user=request.user).values_list('category', flat=True).distinct().exclude(category__isnull=True).exclude(category__exact='')
    context['references'] = PurchaseLog.objects.filter(user=request.user).values_list('reference', flat=True).distinct().exclude(reference__isnull=True).exclude(reference__exact='')
    context['form'] = PurchaseLogForm()
        
    if request.method == "POST":
        form = PurchaseLogForm(request.POST.copy())
        if form.data.get('vendor') == 'None':
            form.data['vendor'] = ''
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
    if change_type == '1':  # Purchased
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