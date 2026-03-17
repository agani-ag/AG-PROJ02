# Django imports
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import Asset

# Forms
from gstbillingapp.forms import AssetForm

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