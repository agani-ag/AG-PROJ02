# Django imports
import csv
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
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
    if total_balance < 0:
        context['balance_status'] = 'Excess Paid'
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
    q = (request.GET.get('q') or '').strip()
    if q:
        purchases_logs = purchases_logs.filter(Q(reference__icontains=q) | Q(vendor__vendor_name__icontains=q))
    paginator = Paginator(purchases_logs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    context['purchases'] = page_obj
    context['page_obj'] = page_obj
    context['total_count'] = paginator.count
    context['querystring'] = params.urlencode()
    context['q'] = q
    context['active_filter'] = request.GET.get('filter', '')
    return render(request, 'purchases/purchases.html', context)


@login_required
def purchases_logs_export(request):
    logs = PurchaseLog.objects.filter(user=request.user).select_related('vendor').order_by('-date')
    f = request.GET.get('filter')
    fmap = {'paid': 0, 'purchased': 1, 'returned': 2, 'others': 3}
    if f in fmap:
        logs = logs.filter(change_type=fmap[f])
    q = (request.GET.get('q') or '').strip()
    if q:
        logs = logs.filter(Q(reference__icontains=q) | Q(vendor__vendor_name__icontains=q))
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="purchases.csv"'
    writer = csv.writer(response)
    writer.writerow(['Date', 'Type', 'Amount', 'Reference', 'Vendor'])
    for p in logs:
        writer.writerow([
            p.date.strftime('%Y-%m-%d %H:%M') if p.date else '',
            p.get_change_type_display(), p.change, p.reference or '',
            p.vendor.vendor_name if p.vendor else '',
        ])
    return response

@login_required
def purchases_logs_overdue(request):
    context = {}
    context['vendor'] = VendorPurchase.objects.filter(user=request.user) \
        .values_list('vendor_name', flat=True) \
        .distinct() \
        .exclude(vendor_name__isnull=True) \
        .exclude(vendor_name__exact='')
    return render(request, 'purchases/purchases_overdue.html', context)

@login_required
def purchases_logs_overdue_api(request):
    vendor = request.GET.get('vendor')
    if vendor:
        purchases = (
            PurchaseLog.objects
            .filter(user=request.user, vendor__vendor_name=vendor)
            .order_by('date')
        )
    else:
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
            'vendor': log.vendor.vendor_name if log.vendor else '',
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
    context['categories'] = PurchaseLog.objects.filter(user=request.user).values_list('category', flat=True).distinct().exclude(category__isnull=True).exclude(category__exact='').order_by('category')
    context['references'] = PurchaseLog.objects.filter(user=request.user).values_list('reference', flat=True).distinct().exclude(reference__isnull=True).exclude(reference__exact='').order_by('reference')
    context['form'] = PurchaseLogForm()
        
    if request.method == "POST":
        form = PurchaseLogForm(request.POST.copy())
        if form.data.get('vendor') == 'None':
            form.data['vendor'] = ''
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.user = request.user
            purchase.change = get_change_type_change(request.POST.get('change_type'), request.POST.get('change'))
            purchase.save()
            return redirect('purchases_logs')
    return render(request,'purchases/purchase_add.html',context)

@login_required
def purchases_logs_delete(request,pid):
    if pid:
        purchases_obj = get_object_or_404(PurchaseLog, user=request.user, id=pid)
        purchases_obj.delete()
    if request.GET.get('vendor'):
        return redirect('purchases_vendor_logs', vendor_purchase_id=request.GET.get('vendor'))
    return redirect('purchases_logs')