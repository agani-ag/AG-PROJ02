# Django imports
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.db.models.functions import Abs, Cast
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Case, When, FloatField, F, Q
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    PurchaseLog, VendorPurchase
)
from ..forms import (
    PurchaseLogForm
)
from ..utils import (
    get_change_type_change,
    get_vendor_instance
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
def purchases_logs_overdue(request):
    return render(request, 'purchases/purchases_overdue.html')

@login_required
def purchases_logs_overdue_api(request):
    purchases = (
        PurchaseLog.objects
        .filter(user=request.user)
        .order_by('date')
    )
    totals = purchases.aggregate(
        total_paid=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_purchased=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_returned=Sum(Case(When(change_type=2, then=F('change')), output_field=FloatField())),
        total_others=Sum(Case(When(change_type=3, then=F('change')), output_field=FloatField())),
    )
    total_paid = abs(totals['total_paid'] or 0)
    total_returned = abs(totals['total_returned'] or 0)
    total_others = abs(totals['total_others'] or 0)
    
    now = timezone.now()

    only_purchases = purchases.filter(change_type=1).annotate(amount_positive=Abs('change')).order_by('date')
    remaining_amount = abs(total_paid) + abs(total_returned) + abs(total_others)
    result = []
    first_overdue_found = False
    first_overdue_id = None
    payment_failed = False
    for log in only_purchases:
        # overdue days
        log.overdue_days = (now - log.date).days if log.date else 0
        invoice_amount = log.amount_positive

        if not payment_failed and remaining_amount >= invoice_amount:
            # covered
            remaining_amount -= invoice_amount
            log.payment_pending = False
        else:
            # once failed, everything is overdue
            if not first_overdue_found:
                first_overdue_found = True
                first_overdue_id = log.id
            payment_failed = True
            log.remaining_amount = remaining_amount
            log.balance_after = abs(remaining_amount - invoice_amount)
            log.payment_pending = True

        result.append({
            'id': log.id,
            'date': log.date.strftime('%d-%m-%Y') if log.date else '',
            'category': log.category,
            'reference': log.reference,
            'amount': invoice_amount,
            'overdue_days': log.overdue_days,
            'payment_pending': log.payment_pending,
            'remaining_amount': log.remaining_amount if log.payment_pending else 0,
            'balance_after': log.balance_after if log.payment_pending else 0,
            'first_overdue': log.id == first_overdue_id
        })
    result = result[::-1]  # reverse to show most recent first
    return JsonResponse(result, safe=False)

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