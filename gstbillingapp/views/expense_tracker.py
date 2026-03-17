# Django imports
from django.db.models import Sum
from django.utils import timezone
from django.contrib import messages
from django.db.models import Min, Max
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

# Models
from ..models import ExpenseTracker

# Forms
from gstbillingapp.forms import ExpenseTrackerForm
import calendar

# ================= Expense Tracker =============================
@login_required
def expense_tracker(request):
    user = request.user
    now = timezone.now()

    current_year = now.year
    current_month = now.month

    # Last month logic
    if current_month == 1:
        last_month = 12
        last_month_year = current_year - 1
    else:
        last_month = current_month - 1
        last_month_year = current_year
    
    context = {}
    
    # Base queryset
    expenses = ExpenseTracker.objects.filter(user=user)

    # Apply filters at the beginning
    reference = request.GET.get("reference")
    category = request.GET.get("category")

    if reference:
        expenses = expenses.filter(reference=reference)
        context["selected_reference"] = reference

    if category:
        expenses = expenses.filter(category=category)
        context["selected_category"] = category

    # Distinct values (from unfiltered queryset if you want all options)
    base_qs = ExpenseTracker.objects.filter(user=user)

    context["categories"] = base_qs.values_list("category", flat=True).distinct()
    context["references"] = base_qs.values_list("reference", flat=True).distinct()

    # Totals based on filtered data
    context["total_current_year"] = (
        expenses.filter(date__year=current_year).aggregate(total=Sum("amount"))["total"] or 0
    )

    context["total_current_month"] = (
        expenses.filter(date__year=current_year, date__month=current_month)
        .aggregate(total=Sum("amount"))["total"] or 0
    )

    context["total_last_month"] = (
        expenses.filter(date__year=last_month_year, date__month=last_month)
        .aggregate(total=Sum("amount"))["total"] or 0
    )

    context["total_expenses"] = expenses.aggregate(total=Sum("amount"))["total"] or 0

    context["total_last_month_name"] = calendar.month_name[last_month]

    # Year range
    years = expenses.aggregate(min_year=Min("date__year"), max_year=Max("date__year"))
    context["start_end_year"] = f"{years['min_year']} - {years['max_year']}"

    context["expenses"] = expenses.order_by("-date")

    return render(request, "expense_tracker/expense_tracker.html", context)

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