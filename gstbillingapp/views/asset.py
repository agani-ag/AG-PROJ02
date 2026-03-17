# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import IntegerField, Sum, Case, When, FloatField, F

# Models
from ..models import Asset, AssetLog
# Forms
from gstbillingapp.forms import AssetForm, AssetLogForm
# Third-party imports
import num2words

# ================= Asset Management =============================
@login_required
def assets(request):
    context = {}
    context['assets'] = Asset.objects.filter(user=request.user)
    return render(request, 'asset/assets.html', context)

@login_required
def asset_add(request):
    context = {}
    context['categories'] = Asset.objects.filter(user=request.user).values_list('category', flat=True).distinct()
    if request.method == "POST":
        asset_form = AssetForm(request.POST)
        if asset_form.is_valid():
            new_asset = asset_form.save(commit=False)
            new_asset.user = request.user
            new_asset.save()
            return redirect('assets')
        else:
            messages.error(request, asset_form.errors)
            context['asset_form'] = asset_form
    context['asset_form'] = AssetForm()
    return render(request, 'asset/asset_edit.html', context)

@login_required
def asset_edit(request, asset_id):
    context = {}
    context['categories'] = Asset.objects.filter(user=request.user).values_list('category', flat=True).distinct()
    asset = get_object_or_404(Asset, id=asset_id, user=request.user)
    if request.method == "POST":
        asset_form = AssetForm(request.POST, instance=asset)
        if asset_form.is_valid():
            updated_asset = asset_form.save(commit=False)
            updated_asset.user = request.user
            updated_asset.save()
            return redirect('assets')
        else:
            messages.error(request, asset_form.errors)
            context['asset_form'] = asset_form
    context['asset_form'] = AssetForm(instance=asset)
    return render(request, 'asset/asset_edit.html', context)

@login_required
def asset_delete(request, asset_id):
    asset = get_object_or_404(Asset, id=asset_id, user=request.user)
    asset.delete()
    messages.success(request, "Asset deleted successfully.")
    return redirect('assets')

@login_required
def asset_log(request, asset_id):
    context = {}
    asset = get_object_or_404(Asset, id=asset_id, user=request.user)
    context['categories'] = AssetLog.objects.filter(asset=asset).values_list('category', flat=True).distinct()
    context['asset'] = asset
    asset_logs = AssetLog.objects.filter(asset=asset)
    totals = asset_logs.aggregate(
        total_credit=Sum(Case(When(change_type=0, then=F('change')), output_field=FloatField())),
        total_debit=Sum(Case(When(change_type=1, then=F('change')), output_field=FloatField())),
        total_credit_count=Sum(Case(When(change_type=0, then=1), output_field=IntegerField())),
        total_debit_count=Sum(Case(When(change_type=1, then=1), output_field=IntegerField()))
    )
    context['total_credit_count'] = int(totals['total_credit_count'] or 0)
    context['total_debit_count'] = int(totals['total_debit_count'] or 0)
    context['total_credit'] = abs(totals['total_credit'] or 0)
    context['total_debit'] = abs(totals['total_debit'] or 0)
    total_transactions = abs(context['total_credit']) - abs(context['total_debit'])
    context['total_transactions'] = total_transactions
    if total_transactions < 0:
        context['transactions_status'] = 'Excess Paid'
    context['total_transactions_word'] = num2words.num2words(abs(int(context['total_transactions'])), lang='en_IN').title()
    if request.GET.get('filter') == 'credit':
        asset_logs = asset_logs.filter(change_type=0)
    elif request.GET.get('filter') == 'debit':
        asset_logs = asset_logs.filter(change_type=1)
    else:
        asset_logs = asset_logs
    if request.GET.get('category'):
        asset_logs = asset_logs.filter(category=request.GET.get('category'))
        context['total_transactions'] = asset_logs.aggregate(total=Sum('change'))['total'] or 0
    context['logs'] = asset_logs.order_by('-date')
    return render(request, 'asset/asset_log.html', context)

@login_required
def asset_log_add(request, asset_id):
    context = {}
    asset = get_object_or_404(Asset, id=asset_id, user=request.user)
    context['categories'] = AssetLog.objects.filter(asset=asset).values_list('category', flat=True).distinct()
    context['asset'] = asset
    if request.method == "POST":
        log_form = AssetLogForm(request.POST)
        if log_form.is_valid():
            new_log = log_form.save(commit=False)
            new_log.asset = asset
            new_log.save()
            return redirect('asset_log', asset_id=asset.id)
        else:
            messages.error(request, log_form.errors)
            context['log_form'] = log_form
    context['log_form'] = AssetLogForm()
    return render(request, 'asset/asset_log_add.html', context)

@login_required
def asset_log_delete(request, log_id):
    log = get_object_or_404(AssetLog, id=log_id, asset__user=request.user)
    asset_id = log.asset.id
    log.delete()
    messages.success(request, "Asset log entry deleted successfully.")
    return redirect('asset_log', asset_id=asset_id)