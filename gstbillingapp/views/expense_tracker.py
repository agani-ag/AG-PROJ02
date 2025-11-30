# Django imports
from django.db.models import Sum
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import ExpenseTracker

# Forms
from gstbillingapp.forms import ExpenseTrackerForm

# ================= Expense Tracker =============================
@login_required
def expense_tracker(request):
    context = {}
    context['total_exp'] = ExpenseTracker.objects.filter(user=request.user).aggregate(Sum('amount'))['amount__sum']
    context['expenses'] = ExpenseTracker.objects.filter(user=request.user).order_by('-date')
    return render(request, 'expense_tracker/expense_tracker.html', context)

@login_required
def expense_tracker_add(request):
    context = {}
    context['categories'] = ExpenseTracker.objects.filter(user=request.user).values_list('category', flat=True).distinct()
    context['references'] = ExpenseTracker.objects.filter(user=request.user).values_list('reference', flat=True).distinct()
    form = ExpenseTrackerForm(initial={'date': timezone.now()})
    if request.method == "POST":
        expense_tracker_form = ExpenseTrackerForm(request.POST)
        if expense_tracker_form.is_valid():
            new_expense = expense_tracker_form.save(commit=False)
            new_expense.user = request.user
            new_expense.save()

            return redirect('expense_tracker')
    context['expense_tracker_form'] = ExpenseTrackerForm()
    return render(request, 'expense_tracker/expense_tracker_edit.html', context)

@login_required
def expense_tracker_delete(request, expense_id):
    expense = get_object_or_404(ExpenseTracker, id=expense_id, user=request.user)
    expense.delete()
    messages.success(request, "Expense deleted successfully.")
    return redirect('expense_tracker')