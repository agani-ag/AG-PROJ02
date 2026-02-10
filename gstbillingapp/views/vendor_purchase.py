# Django imports
from django.http import JsonResponse
from django.db.models.functions import Abs, Cast
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Case, When, FloatField, F, Q

# Models
from ..models import VendorPurchase, PurchaseLog
from ..forms import VendorPurchaseForm, PurchaseLogForm
from ..utils import (
    get_change_type_change,
    get_vendor_instance
)
import num2words

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


@login_required
def purchases_vendor_logs(request, vendor_purchase_id):
    context = {}
    context['vendor'] = get_object_or_404(VendorPurchase, user=request.user, id=vendor_purchase_id)
    purchases_logs = PurchaseLog.objects.filter(user=request.user, vendor_id=vendor_purchase_id).order_by('-date')
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
    return render(request, 'vendor_purchase/purchases_vendor_logs.html', context)

@login_required
def purchases_logs_add_api(request):
    if request.method == "POST" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        form = PurchaseLogForm(request.POST.copy())

        if form.data.get('vendor') == 'None':
            form.data['vendor'] = ''

        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.user = request.user
            purchase.change = get_change_type_change(
                request.POST.get('change_type'),
                request.POST.get('change')
            )
            purchase.save()
            return JsonResponse({"success": True})

        # Return validation errors
        return JsonResponse({"success": False, "errors": form.errors})

    # If GET, return dropdown data
    categories = list(PurchaseLog.objects.filter(user=request.user)
                      .values_list('category', flat=True)
                      .distinct()
                      .exclude(category__isnull=True)
                      .exclude(category__exact=''))

    references = list(PurchaseLog.objects.filter(user=request.user)
                      .values_list('reference', flat=True)
                      .distinct()
                      .exclude(reference__isnull=True)
                      .exclude(reference__exact=''))

    return JsonResponse({
        "categories": categories,
        "references": references,
    })

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