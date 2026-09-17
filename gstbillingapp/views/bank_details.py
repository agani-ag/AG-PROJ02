# Django imports
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, Case, When, FloatField, F, Q
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
    qs = BankDetails.objects.filter(user=request.user)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(account_name__icontains=q) | Q(account_number__icontains=q) | Q(bank_name__icontains=q))
    paginator = Paginator(qs.order_by('-id'), 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'bank_details/bank_details.html', {
        'bank_details': page_obj, 'page_obj': page_obj, 'total_count': paginator.count,
        'q': q, 'querystring': params.urlencode(),
    })

@login_required
def bank_details_add(request):
    if request.method == "POST":
        bank_details_form = BankDetailsForm(request.POST, user=request.user)
        if bank_details_form.is_valid():
            new_bank_detail = bank_details_form.save(commit=False)
            new_bank_detail.user = request.user
            new_bank_detail.save()

            return redirect('bank_details')
    context = {}
    context['bank_details_form'] = BankDetailsForm(user=request.user)
    return render(request, 'bank_details/bank_details_edit.html', context)

@login_required
def bank_details_edit(request, pk):
    bank_detail = get_object_or_404(BankDetails, pk=pk, user=request.user)
    if request.method == "POST":
        bank_details_form = BankDetailsForm(request.POST, instance=bank_detail, user=request.user)
        if bank_details_form.is_valid():
            bank_details_form.save()
            return redirect('bank_details')
    context = {}
    context['bank_details_form'] = BankDetailsForm(instance=bank_detail, user=request.user)
    return render(request, 'bank_details/bank_details_edit.html', context)

@login_required
def bank_details_delete(request, pk):
    bank_detail = get_object_or_404(BankDetails, pk=pk, user=request.user)
    bank_detail.delete()
    return redirect('bank_details')

# ===================== Cheque Leaf views =============================
@login_required
def cheque_leafs(request):
    context = {}
    logs = ChequeLeaf.objects.filter(user=request.user).order_by('-clearance_date')
    cleared = ['CLEARED']
    pending = ['ISSUED','PRESENTED','BOUNCED',]
    others = ['UNUSED','CANCELLED','STOPPED']
    totals = logs.aggregate(
        total_cleared=Sum(Case(When(status__in=cleared, then=F('amount')), output_field=FloatField())),
        total_pending=Sum(Case(When(status__in=pending, then=F('amount')), output_field=FloatField())),
        total_others=Sum(Case(When(status__in=others, then=F('amount')), output_field=FloatField())),
    )
    # Fill in context with totals, using 0 if None
    context['total_cleared'] = totals['total_cleared'] or 0
    context['total_pending'] = totals['total_pending'] or 0
    context['total_others'] = totals['total_others'] or 0
    if request.GET.get('filter') == 'cleared':
        logs = logs.filter(status__in=cleared)
    elif request.GET.get('filter') == 'pending':
        logs = logs.filter(status__in=pending)
    elif request.GET.get('filter') == 'others':
        logs = logs.filter(status__in=others)
    else:
        logs = logs.all()
    if request.GET.get('period') == 'this_month':
        logs = logs.filter(clearance_date__month=timezone.now().month, clearance_date__year=timezone.now().year)
        context['selected_period'] = "This Month"
    elif request.GET.get('period') == 'next_month':
        next_month = timezone.now().month + 1 if timezone.now().month != 12 else 1
        next_month_year = timezone.now().year if timezone.now().month != 12 else timezone.now().year + 1
        logs = logs.filter(clearance_date__month=next_month, clearance_date__year=next_month_year)
        context['selected_period'] = "Next Month"
    elif request.GET.get('period') == 'previous_month':
        logs = logs.filter(clearance_date__lt=timezone.now().replace(day=1))
        context['selected_period'] = "Previous Month"
    else:
        logs = logs.all()
    q = (request.GET.get('q') or '').strip()
    if q:
        logs = logs.filter(Q(payee_name__icontains=q) | Q(cheque_number__icontains=q))
    paginator = Paginator(logs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    context['cheque_leafs'] = page_obj
    context['page_obj'] = page_obj
    context['total_count'] = paginator.count
    context['querystring'] = params.urlencode()
    context['q'] = q
    context['active_filter'] = request.GET.get('filter', '')
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
    # Scoped to this business - a business can only reach its OWN cheque leaves.
    cheque_leaf = get_object_or_404(ChequeLeaf, pk=pk, user=request.user)
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
    # Scoped to this business - a business can only reach its OWN cheque leaves.
    cheque_leaf = get_object_or_404(ChequeLeaf, pk=pk, user=request.user)
    cheque_leaf.delete()
    messages.success(request, "Cheque leaf entry deleted successfully.")
    return redirect('cheque_leafs')
