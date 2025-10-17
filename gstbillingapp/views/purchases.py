# Django imports
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import UserProfile
from ..models import PurchaseLog

# Third-party libraries
import json
import datetime

# ================= Purchases =============================
@login_required
def purchases(request):
    context = {}
    # context['purchases'] = PurchaseLog.objects.filter(user=request.user).order_by('-date')
    context['total_p'] = PurchaseLog.objects.filter(user=request.user, ptype="purchase").aggregate(Sum('amount'))['amount__sum']
    context['total_pp'] = PurchaseLog.objects.filter(user=request.user, ptype="paid").aggregate(Sum('amount'))['amount__sum']
    context['total_pb'] = PurchaseLog.objects.filter(user=request.user).aggregate(Sum('amount'))['amount__sum']

    current_date = datetime.datetime.now().date()
    purchases = PurchaseLog.objects.filter(user=request.user).order_by('date')
    purchases_with_days = []
    temp1,temp2 = 0, 0
    total_paid = context['total_pp'] if context['total_pp'] else 0
    for purchase in purchases:
        days_difference = (current_date - purchase.date.date()).days
        if purchase.ptype == 'purchase':
            total_paid = total_paid + purchase.amount
            if total_paid < 0 and temp2 == 0:
                temp1 = abs(total_paid)
                temp2 = 1
            else:
                temp1 = 'colour2'
            colour = temp1 if total_paid < 0 else 'colour1'
        else:
            colour = 'colour2' if total_paid < 0 else 'colour1'
        purchase_data = purchase.__dict__
        purchase_data['days'] = days_difference
        purchase_data['colour'] = colour
        if purchase_data['days'] > 80 and purchase.ptype == 'purchase':
            if purchase_data['colour'] != 'colour1':
                messages.error(request, f'You Have Pending Purchase Bill of ₹{abs(purchase.amount)} - Ref.No {purchase.addon2}')

        purchases_with_days.append(purchase_data)
    context['purchases'] = purchases_with_days[::-1]
    # context['purchases'] = purchases_with_days
    
    return render(request, 'purchases/purchases.html', context)

@login_required
def purchases_add(request):
    data = {}
    if request.method == 'POST':
        date = request.POST['date']
        ptype = request.POST['ptype']
        amount = request.POST['amount']
        addon1 = request.POST['addon1']
        addon2 = request.POST['addon2']
        category = request.POST['purchase_category']
        category_other = request.POST['other_category']
        if category == 'Other' and ptype == 'purchase':
            if not category_other:
                messages.error(request, 'Please provide a valid category name.')
                return redirect('purchases_add')
            category_save = category_other
            business_config = get_object_or_404(UserProfile, user=request.user)
            bc = json.loads(business_config.business_config)
            bc['category'].append(category_other)
            business_config.business_config = json.dumps(bc)
            business_config.save()
        else:
            category_save = category
        if ptype == 'purchase':
            if int(amount) > 0 :
                amount = -int(amount)
        else:
            amount = abs(int(amount))
        purchase_log = PurchaseLog(user=request.user, date=date, ptype=ptype,
                category=category_save, amount=amount, addon1=addon1, addon2=addon2)
        purchase_log.save()
        return redirect('purchases')
    
    data['category'] = UserProfile.objects.filter(user=request.user).values('business_config').first()
    if not data['category']['business_config']:
        business_config = get_object_or_404(UserProfile, user=request.user)
        business_config.business_config=json.dumps({'category': []})
        business_config.save()
        data['category'] = []
        return render(request,'purchases/purchase_add.html',data)
    data['category'] = json.loads(data['category']['business_config']).get('category')
    return render(request,'purchases/purchase_add.html',data)

@login_required
def purchases_edit(request,pid):
    data = {}
    purchase_log = get_object_or_404(PurchaseLog, user=request.user, id=pid)
    data['plog'] = purchase_log
    if request.method == 'POST':
        pid = int(pid)
        date = request.POST['date']
        ptype = request.POST['ptype']
        amount = request.POST['amount']
        addon1 = request.POST['addon1']
        addon2 = request.POST['addon2']
        category = request.POST['purchase_category']
        category_other = request.POST['other_category']
        print(category, category_other)
        if category == 'Other' and ptype == 'purchase':
            if not category_other:
                messages.error(request, 'Please provide a valid category name.')
                return redirect('purchases_edit', pid=pid)
            category_save = category_other
            business_config = get_object_or_404(UserProfile, user=request.user)
            bc = json.loads(business_config.business_config)
            bc['category'].append(category_other)
            business_config.business_config = json.dumps(bc)
            business_config.save()
        else:
            category_save = category
        if ptype == 'purchase':
            if int(amount) > 0 :
                amount = -int(amount)
        else:
            amount = abs(int(amount))
        purchase_log.date = date
        purchase_log.ptype=ptype
        purchase_log.amount=amount
        purchase_log.addon1=addon1
        purchase_log.addon2=addon2
        purchase_log.category=category_save
        purchase_log.save()
        messages.success(request, 'Your changes have been saved successfully.')
        return redirect('purchases_edit',pid)
    data['category'] = UserProfile.objects.filter(user=request.user).values('business_config').first()
    data['category'] = json.loads(data['category']['business_config']).get('category')
    return render(request,'purchases/purchase_edit.html',data)

@login_required
def purchases_delete(request,pid):
    if pid:
        purchases_obj = get_object_or_404(PurchaseLog, user=request.user, id=pid)
        purchases_obj.delete()
    return redirect('purchases')