# Django imports
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import (
    BankDetails
)

# Forms
from ..forms import BankDetailsForm


# ===================== Bank Details views =============================
@login_required
def bank_details(request):
    context = {}
    context['bank_details'] = BankDetails.objects.filter(user=request.user)
    return render(request, 'bank_details/bank_details.html', context)


@login_required
def bank_details_add(request):
    if request.method == "POST":
        bank_details_form = BankDetailsForm(request.POST)
        if bank_details_form.is_valid():
            new_bank_detail = bank_details_form.save(commit=False)
            new_bank_detail.user = request.user
            new_bank_detail.save()

            return redirect('bank_details')
    context = {}
    context['bank_details_form'] = BankDetailsForm()
    return render(request, 'bank_details/bank_details_edit.html', context)

@login_required
def bank_details_edit(request, pk):
    bank_detail = get_object_or_404(BankDetails, pk=pk)
    if request.method == "POST":
        bank_details_form = BankDetailsForm(request.POST, instance=bank_detail)
        if bank_details_form.is_valid():
            bank_details_form.save()
            return redirect('bank_details')
    context = {}
    context['bank_details_form'] = BankDetailsForm(instance=bank_detail)
    return render(request, 'bank_details/bank_details_edit.html', context)

@login_required
def bank_details_delete(request, pk):
    bank_detail = get_object_or_404(BankDetails, pk=pk)
    bank_detail.delete()
    return redirect('bank_details')