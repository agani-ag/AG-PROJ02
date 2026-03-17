# Django imports
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
# Models
from ..models import (
    BankDetails, ChequeLeaf
)
# Forms
from ..forms import (
    BankDetailsForm ,ChequeLeafForm
)
# Python imports
import json

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

# ===================== Cheque Leaf views =============================
@login_required
def cheque_leafs(request):
    context = {}
    context['cheque_leafs'] = ChequeLeaf.objects.filter(user=request.user)
    return render(request, 'bank_details/cheque_leafs.html', context)

@login_required
def cheque_leaf_add(request):
    if request.method == "POST":
        cheque_leaf_form = ChequeLeafForm(request.POST)
        if cheque_leaf_form.is_valid():
            new_cheque_leaf = cheque_leaf_form.save(commit=False)
            new_cheque_leaf.user = request.user
            new_cheque_leaf.save()
            return redirect('cheque_leafs')
        else:
            messages.error(request, cheque_leaf_form.errors)
    context = {}
    context['cheque_leaf_form'] = ChequeLeafForm()
    context['banks'] = ChequeLeaf.objects.filter(user=request.user).values_list('bank', flat=True).distinct()
    context['branches'] = ChequeLeaf.objects.filter(user=request.user).values_list('branch', flat=True).distinct()
    context['account_numbers'] = ChequeLeaf.objects.filter(user=request.user).values_list('account_number', flat=True).distinct()
    return render(request, 'bank_details/cheque_leaf_edit.html', context)

@login_required
def cheque_leaf_edit(request, pk):
    cheque_leaf = get_object_or_404(ChequeLeaf, pk=pk)
    context = {}
    context['banks'] = ChequeLeaf.objects.filter(user=request.user).values_list('bank', flat=True).distinct()
    context['branches'] = ChequeLeaf.objects.filter(user=request.user).values_list('branch', flat=True).distinct()
    context['account_numbers'] = ChequeLeaf.objects.filter(user=request.user).values_list('account_number', flat=True).distinct()
    if request.method == "POST":
        cheque_leaf_form = ChequeLeafForm(request.POST, instance=cheque_leaf)
        if cheque_leaf_form.is_valid():
            cheque_leaf_form.save()
            return redirect('cheque_leafs')
    context['cheque_leaf_form'] = ChequeLeafForm(instance=cheque_leaf)
    return render(request, 'bank_details/cheque_leaf_edit.html', context)

@login_required
def cheque_leaf_delete(request, pk):
    cheque_leaf = get_object_or_404(ChequeLeaf, pk=pk)
    cheque_leaf.delete()
    messages.success(request, "Cheque leaf entry deleted successfully.")
    return redirect('cheque_leafs')

@csrf_exempt
def cheque_leaf_reminder_api(request):
    """
    API endpoint to fetch upcoming cheque clearances for the logged-in user.
    Accepts an optional 'user_ids' parameter (comma-separated integers) to filter by specific users.
    Returns a JSON response with clearance details and a formatted message.
    Example request:
    GET /api/cheque_leaf_reminder/?user_ids=1,2,3 or POST with JSON body {"user_ids": [1, 2, 3]}
    """
    # --- Parse user_ids ---
    user_ids = []
    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))
            user_ids = body.get('user_ids', [])
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON body.'}, status=400)
    else:
        raw = request.GET.get('user_ids', '')
        if raw:
            try:
                user_ids = [int(uid.strip()) for uid in raw.split(',') if uid.strip()]
            except ValueError:
                return JsonResponse({'status': 'error', 'message': 'user_ids must be comma-separated integers.'}, status=400)

    if not user_ids:
        return JsonResponse({'status': 'error', 'message': 'user_ids is required (non-empty array).'}, status=400)
    
    active_status = ['ISSUED', 'PRESENTED']
    clearance_cheque_leafs = ChequeLeaf.objects.filter(
        user__id__in=user_ids,
        clearance_date__gte=timezone.now().date(),
        status__in=active_status
    )

    markdown = "*💰 Cheque Clearance Reminder*\n\n"

    if not clearance_cheque_leafs.exists():
        markdown += "_No upcoming cheque clearances._"
    else:
        for cheque in clearance_cheque_leafs:
            Brand = str(cheque.user if cheque.user else "N/A")
            markdown += (
                f"*Cheque No:* `{cheque.cheque_number}`\n"
                f"*Bank:* {cheque.bank}\n"
                f"*Payee:* {cheque.payee_name}\n"
                f"*Amount:* ₹{cheque.amount}\n"
                f"*Clearance Date:* {cheque.clearance_date}\n"
                f"*Status:* {cheque.status}\n"
                f"*Brand:* {Brand.upper()}\n"
                f"----------------------\n"
            )
    
    return JsonResponse({
        "status": "success",
        "count": clearance_cheque_leafs.count(),
        "data": list(clearance_cheque_leafs.values()),
        "markdown": markdown
    })