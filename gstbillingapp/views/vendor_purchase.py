# Django imports
import csv
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
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
def _filtered_vendors(request):
    qs = VendorPurchase.objects.filter(user=request.user).order_by('vendor_name')
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(vendor_name__icontains=q) | Q(vendor_phone__icontains=q) | Q(vendor_gst__icontains=q))
    return qs, q


@login_required
def vendors_purchase(request):
    qs, q = _filtered_vendors(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'vendor_purchase/vendors_purchase.html', {
        'vendors': page_obj, 'page_obj': page_obj, 'total_count': paginator.count,
        'q': q, 'querystring': params.urlencode(),
    })


@login_required
def vendors_purchase_export(request):
    qs, _q = _filtered_vendors(request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="vendors.csv"'
    writer = csv.writer(response)
    writer.writerow(['Vendor Name', 'Address', 'Phone', 'GST'])
    for v in qs:
        writer.writerow([v.vendor_name, v.vendor_address or '', v.vendor_phone or '', v.vendor_gst or ''])
    return response


@login_required
def vendor_purchase_edit(request, vendor_purchase_id):
    vendor_purchase_obj = get_object_or_404(VendorPurchase, user=request.user, id=vendor_purchase_id)
    if request.method == "POST":
        vendor_purchase_form = VendorPurchaseForm(request.POST, instance=vendor_purchase_obj, user=request.user)
        if vendor_purchase_form.is_valid():
            new_vendor_purchase = vendor_purchase_form.save()
            return redirect('vendors_purchase')
    context = {}
    context['vendor_purchase_form'] = VendorPurchaseForm(instance=vendor_purchase_obj, user=request.user)
    context['id'] = vendor_purchase_obj.id
    return render(request, 'vendor_purchase/vendor_purchase_edit.html', context)


@login_required
def vendor_purchase_add(request):
    if request.method == "POST":
        vendor_purchase_form = VendorPurchaseForm(request.POST, user=request.user)
        if vendor_purchase_form.is_valid():
            new_vendor_purchase = vendor_purchase_form.save(commit=False)
            new_vendor_purchase.user = request.user
            new_vendor_purchase.save()

            return redirect('vendors_purchase')
    context = {}
    context['vendor_purchase_form'] = VendorPurchaseForm(user=request.user)
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
    if request.method == "POST":
        log_id = request.POST.get("log_id")
        log_obj = get_object_or_404(PurchaseLog, user=request.user, id=log_id)
        log_obj.delete()
    context = {}
    today = timezone.now().date()
    context['today'] = today
    vendor = get_object_or_404(VendorPurchase, user=request.user, id=vendor_purchase_id)
    context['vendor'] = vendor
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
    context['purchases'] = purchases_logs
    # If GET, return dropdown data
    categories = (PurchaseLog.objects.filter(vendor=vendor).exclude(category__isnull=True).exclude(category__exact='')
        .values_list('category', flat=True).distinct()
    )
    context['categories'] = list(categories)
    references = (PurchaseLog.objects.filter(vendor=vendor).exclude(reference__isnull=True).exclude(reference__exact='')
        .values_list('reference', flat=True).distinct()
    )
    context['references'] = list(references)
    return render(request, 'vendor_purchase/purchases_vendor_logs.html', context)

@login_required
def purchases_logs_add_api(request):
    if request.method == "POST" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        post_data = request.POST.copy()
        
        # Reference
        reference1 = post_data.get('reference1', '').strip()
        reference2 = post_data.get('reference2', '').strip()
        # Fallback logic
        if reference1:  # If reference1 has data
            post_data['reference'] = reference1
        elif reference2:  # If reference1 empty, use reference2
            post_data['reference'] = reference2
        else:
            return JsonResponse({"success": False, "errors": {"Reference": ["This field is required."]}})
        
        # Category
        category1 = post_data.get('category1', '').strip()
        category2 = post_data.get('category2', '').strip()
        # Fallback logic
        if category1:  # If category1 has data
            post_data['category'] = category1
        elif category2:  # If category1 empty, use category2
            post_data['category'] = category2
        else:
            return JsonResponse({"success": False, "errors": {"Category": ["This field is required."]}})
        if post_data.get('category2') != '':
            post_data['category'] = post_data.get('category2')
        
        # Vendor
        if post_data.get('vendor') == 'None':
            post_data['vendor'] = ''
        
        form = PurchaseLogForm(post_data)

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