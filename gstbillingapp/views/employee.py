"""Desktop management of a business's mobile employees (staff of ONE business)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib.auth.models import User

from ..models import Employee, Customer, Invoice
from ..forms import EmployeeForm
from ..mobile_auth import mint_employee_token, mint_customer_token

import json


def _invoice_total(invoice_json):
    """The grand total stored inside an invoice's JSON (amounts live there, not in columns)."""
    try:
        return round(float(json.loads(invoice_json).get('invoice_total_amt_with_gst', 0) or 0), 2)
    except (ValueError, TypeError):
        return 0.0


def _business_by_code(code):
    """A shareable business for a pasted code (its business_uid), or None.

    Sharing is opt-in: a business is only reachable by code when it has turned on
    `sharing_enabled`, so a guessed code can't attach a business that never agreed.
    """
    code = (code or "").strip().upper()
    if not code:
        return None
    return (User.objects.filter(userprofile__business_uid__iexact=code,
                                userprofile__sharing_enabled=True)
            .select_related("userprofile").first())


def _set_businesses_by_code(request, emp):
    """Set the employee's extra shared businesses from the pasted share codes.

    The employer's own business is always covered (see Employee.covered_businesses),
    so the M2M holds only the ADDITIONAL shared businesses — never the home one.
    """
    ids = []
    for code in request.POST.getlist("business_codes"):
        biz = _business_by_code(code)
        if biz and biz.id != emp.business_id:
            ids.append(biz.id)
    emp.businesses.set(ids)


def _shared_context(emp=None):
    """The employee's shared businesses (excluding the home business). Each carries an
    `active` flag: a business that has since turned sharing OFF is shown but inert."""
    shared = []
    if emp:
        for b in emp.businesses.exclude(id=emp.business_id).select_related("userprofile"):
            p = getattr(b, "userprofile", None)
            shared.append({
                "code": (p.business_uid if p else "") or "",
                "name": (p.business_brand or p.business_title if p else None) or b.username,
                "active": bool(p and p.sharing_enabled),
            })
    return {"shared_businesses": shared}


@login_required
def employees(request):
    return render(request, "employees/employees.html", {
        "employees": Employee.objects.filter(business=request.user),
    })


@login_required
def employee_add(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save(commit=False)
            emp.business = request.user
            emp.save()
            _set_businesses_by_code(request, emp)
            messages.success(request, f"Employee '{emp.name}' added.")
            return redirect("employees")
        return render(request, "employees/employee_edit.html", {"error_message": form.errors, "form": form})
    return render(request, "employees/employee_edit.html", {"form": EmployeeForm()})


@login_required
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk, business=request.user)
    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=emp)
        if form.is_valid():
            form.save()
            _set_businesses_by_code(request, emp)
            messages.success(request, "Employee updated.")
            return redirect("employees")
        context = {"employee": emp, "error_message": form.errors, "form": form}
        context.update(_shared_context(emp))
        return render(request, "employees/employee_edit.html", context)
    context = {"employee": emp, "form": EmployeeForm(instance=emp)}
    context.update(_shared_context(emp))
    return render(request, "employees/employee_edit.html", context)


@login_required
def business_share_lookup(request):
    """Validate a pasted share code → the business it unlocks (for the employee form)."""
    biz = _business_by_code(request.GET.get("code"))
    if not biz:
        return JsonResponse({"ok": False, "message": "No shared business found for that code."})
    if biz.id == request.user.id:
        return JsonResponse({"ok": False, "message": "That's your own business — already covered."})
    p = getattr(biz, "userprofile", None)
    return JsonResponse({
        "ok": True,
        "code": (p.business_uid if p else "") or "",
        "name": (p.business_brand or p.business_title if p else None) or biz.username,
    })


@login_required
def employee_delete(request, pk):
    if request.method == "POST":
        get_object_or_404(Employee, pk=pk, business=request.user).delete()
        messages.success(request, "Employee removed.")
    return redirect("employees")


@login_required
def employee_invoices(request, pk):
    """
    An employee's owned invoices — the ones credited to them via 'Map to Employee'.
    Native replacement for the external app's employee_invoices report: month and
    date-range filters, grand total and count. Amounts are read from invoice_json.
    """
    emp = get_object_or_404(Employee, pk=pk, business=request.user)
    qs = Invoice.objects.filter(user=request.user, assigned_employee=emp).order_by('-invoice_date', '-id')

    # Distinct months present, for the filter dropdown.
    months_list = [
        {'value': d.strftime('%Y-%m'), 'label': d.strftime('%B %Y')}
        for d in qs.dates('invoice_date', 'month', order='DESC')
    ]

    selected_month = request.GET.get('month', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if selected_month:
        try:
            year, month = selected_month.split('-')
            qs = qs.filter(invoice_date__year=int(year), invoice_date__month=int(month))
        except ValueError:
            pass
    if date_from:
        qs = qs.filter(invoice_date__gte=date_from)
    if date_to:
        qs = qs.filter(invoice_date__lte=date_to)

    rows, grand_total = [], 0.0
    for inv in qs.select_related('invoice_customer'):
        amount = _invoice_total(inv.invoice_json)
        grand_total += amount
        rows.append({
            'id': inv.id, 'number': inv.invoice_number, 'date': inv.invoice_date,
            'is_gst': inv.is_gst, 'amount': amount,
            'customer': inv.invoice_customer.customer_name if inv.invoice_customer else 'N/A',
        })

    return render(request, 'employees/employee_invoices.html', {
        'employee': emp, 'rows': rows, 'months_list': months_list,
        'selected_month': selected_month, 'date_from': date_from, 'date_to': date_to,
        'grand_total': round(grand_total, 2), 'record_count': len(rows),
    })


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
