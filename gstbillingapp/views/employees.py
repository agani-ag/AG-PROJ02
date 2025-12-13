# Django imports
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from django.db.models import Q

# Models
from ..models import Employee, UserProfile

# Python imports
import json


# ================= Employee Views =============================
@login_required
def employees(request):
    """List all employees"""
    user_profile = request.user.userprofile
    
    # Get search query
    search_query = request.GET.get('search', '')
    
    employees_list = Employee.objects.filter(user_profile=user_profile)
    
    if search_query:
        employees_list = employees_list.filter(
            Q(employee_name__icontains=search_query) |
            Q(employee_userid__icontains=search_query) |
            Q(employee_phone__icontains=search_query) |
            Q(employee_email__icontains=search_query)
        )
    
    employees_list = employees_list.order_by('-date_joined')
    
    context = {
        'employees': employees_list,
        'search_query': search_query,
    }
    
    return render(request, 'employees/employees.html', context)


@login_required
def employee_add(request):
    """Add new employee"""
    user_profile = request.user.userprofile
    
    if request.method == 'POST':
        try:
            employee_name = request.POST.get('employee_name')
            employee_phone = request.POST.get('employee_phone')
            employee_email = request.POST.get('employee_email', '')
            employee_userid = request.POST.get('employee_userid')
            employee_password = request.POST.get('employee_password')
            role = request.POST.get('role', 'sales')
            
            # Permissions
            can_create_invoice = request.POST.get('can_create_invoice') == 'on'
            can_delete_invoice = request.POST.get('can_delete_invoice') == 'on'
            can_view_reports = request.POST.get('can_view_reports') == 'on'
            can_manage_inventory = request.POST.get('can_manage_inventory') == 'on'
            can_manage_customers = request.POST.get('can_manage_customers') == 'on'
            
            # Validation
            if not all([employee_name, employee_phone, employee_userid, employee_password]):
                messages.error(request, 'All required fields must be filled.')
                return redirect('employee_add')
            
            # Check if employee userid already exists
            if Employee.objects.filter(employee_userid=employee_userid.lower()).exists():
                messages.error(request, f'Employee with ID {employee_userid} already exists.')
                return redirect('employee_add')
            
            # Create employee
            employee = Employee.objects.create(
                user_profile=user_profile,
                employee_name=employee_name.upper(),
                employee_phone=employee_phone,
                employee_email=employee_email.lower() if employee_email else '',
                employee_userid=employee_userid.lower(),
                employee_password=make_password(employee_password),
                role=role,
                can_create_invoice=can_create_invoice,
                can_delete_invoice=can_delete_invoice,
                can_view_reports=can_view_reports,
                can_manage_inventory=can_manage_inventory,
                can_manage_customers=can_manage_customers,
            )
            
            messages.success(request, f'Employee {employee.employee_name} created successfully!')
            return redirect('employees')
            
        except Exception as e:
            messages.error(request, f'Error creating employee: {str(e)}')
            return redirect('employee_add')
    
    # Get suggested employee ID
    last_emp = Employee.objects.filter(user_profile=user_profile).order_by('-id').first()
    if last_emp:
        try:
            last_num = int(last_emp.employee_userid.replace('emp', '').replace('EMP', ''))
            suggested_id = f'EMP{last_num + 1:03d}'
        except:
            suggested_id = 'EMP001'
    else:
        suggested_id = 'EMP001'
    
    context = {
        'suggested_id': suggested_id,
    }
    
    return render(request, 'employees/employee_add.html', context)


@login_required
def employee_edit(request, employee_id):
    """Edit employee"""
    user_profile = request.user.userprofile
    employee = get_object_or_404(Employee, id=employee_id, user_profile=user_profile)
    
    if request.method == 'POST':
        try:
            employee.employee_name = request.POST.get('employee_name').upper()
            employee.employee_phone = request.POST.get('employee_phone')
            employee.employee_email = request.POST.get('employee_email', '').lower()
            employee.role = request.POST.get('role', 'sales')
            employee.is_active = request.POST.get('is_active') == 'on'
            
            # Update password only if provided
            new_password = request.POST.get('employee_password')
            if new_password:
                employee.employee_password = make_password(new_password)
            
            # Permissions
            employee.can_create_invoice = request.POST.get('can_create_invoice') == 'on'
            employee.can_delete_invoice = request.POST.get('can_delete_invoice') == 'on'
            employee.can_view_reports = request.POST.get('can_view_reports') == 'on'
            employee.can_manage_inventory = request.POST.get('can_manage_inventory') == 'on'
            employee.can_manage_customers = request.POST.get('can_manage_customers') == 'on'
            
            employee.save()
            
            messages.success(request, f'Employee {employee.employee_name} updated successfully!')
            return redirect('employees')
            
        except Exception as e:
            messages.error(request, f'Error updating employee: {str(e)}')
            return redirect('employee_edit', employee_id=employee_id)
    
    context = {
        'employee': employee,
    }
    
    return render(request, 'employees/employee_edit.html', context)


@login_required
def employee_delete(request):
    """Delete employee (AJAX)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            employee_id = data.get('employee_id')
            
            user_profile = request.user.userprofile
            employee = get_object_or_404(Employee, id=employee_id, user_profile=user_profile)
            
            employee_name = employee.employee_name
            employee.delete()
            
            return JsonResponse({
                'status': 'success',
                'message': f'Employee {employee_name} deleted successfully!'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error deleting employee: {str(e)}'
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


@login_required
def employee_toggle_status(request):
    """Toggle employee active status (AJAX)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            employee_id = data.get('employee_id')
            
            user_profile = request.user.userprofile
            employee = get_object_or_404(Employee, id=employee_id, user_profile=user_profile)
            
            employee.is_active = not employee.is_active
            employee.save()
            
            status_text = 'activated' if employee.is_active else 'deactivated'
            
            return JsonResponse({
                'status': 'success',
                'message': f'Employee {employee.employee_name} {status_text}!',
                'is_active': employee.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error updating status: {str(e)}'
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
