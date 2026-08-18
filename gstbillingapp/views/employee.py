"""Desktop management of a business's mobile employees (staff of ONE business)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib.auth.models import User

from ..models import Employee, Customer
from ..forms import EmployeeForm
from ..mobile_auth import mint_employee_token, mint_customer_token


def _all_businesses():
    """Every business in the system (any user with a profile), brand-first order."""
    return (User.objects.filter(userprofile__isnull=False)
            .select_related("userprofile")
            .order_by("userprofile__business_brand", "userprofile__business_title"))


def _set_businesses(request, emp):
    """Store the chosen coverage — any business the operator picked."""
    allowed = set(_all_businesses().values_list("id", flat=True))
    chosen = [int(x) for x in request.POST.getlist("businesses") if x.isdigit() and int(x) in allowed]
    emp.businesses.set(chosen)


def _group_context(request, emp=None):
    return {
        "group_businesses": _all_businesses(),
        "selected_ids": set(emp.businesses.values_list("id", flat=True)) if emp else set(),
    }


@login_required
def employees(request):
    return render(request, "employees/employees.html", {
        "employees": Employee.objects.filter(business=request.user),
    })


@login_required
def employee_add(request):
    context = dict(_group_context(request))
    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save(commit=False)
            emp.business = request.user
            emp.save()
            _set_businesses(request, emp)
            messages.success(request, f"Employee '{emp.name}' added.")
            return redirect("employees")
        context["error_message"] = form.errors
        context["form"] = form
        return render(request, "employees/employee_edit.html", context)
    context["form"] = EmployeeForm()
    return render(request, "employees/employee_edit.html", context)


@login_required
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk, business=request.user)
    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=emp)
        if form.is_valid():
            form.save()
            _set_businesses(request, emp)
            messages.success(request, "Employee updated.")
            return redirect("employees")
        context = {"employee": emp, "error_message": form.errors}
        context.update(_group_context(request, emp))
        context["form"] = form
        return render(request, "employees/employee_edit.html", context)
    context = {"employee": emp, "form": EmployeeForm(instance=emp)}
    context.update(_group_context(request, emp))
    return render(request, "employees/employee_edit.html", context)


@login_required
def employee_delete(request, pk):
    if request.method == "POST":
        get_object_or_404(Employee, pk=pk, business=request.user).delete()
        messages.success(request, "Employee removed.")
    return redirect("employees")


@login_required
def employee_mobile_link(request, pk):
    """Signed /m/employee/ URL to paste into this employee's SyncUp link list."""
    emp = get_object_or_404(Employee, pk=pk, business=request.user)
    url = request.build_absolute_uri("/m/employee/") + "?t=" + mint_employee_token(emp)
    return JsonResponse({"ok": True, "url": url, "name": emp.name, "email": emp.email})


@login_required
def employee_revoke(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    emp = get_object_or_404(Employee, pk=pk, business=request.user)
    emp.token_version += 1
    emp.save()
    return JsonResponse({"ok": True})


@login_required
def customer_mobile_link(request, customer_id):
    """Signed /m/customer/ URL to paste into this customer's SyncUp link list."""
    c = get_object_or_404(Customer, id=customer_id, user=request.user)
    url = request.build_absolute_uri("/m/customer/") + "?t=" + mint_customer_token(c)
    return JsonResponse({"ok": True, "url": url})
