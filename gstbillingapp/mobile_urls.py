# Django imports
from django.urls import path, include

# Local imports
from .views.mobile import auth, dashboard

urlpatterns = [
    # ================= Authentication URLs =================
    # Login Selection
    path('', auth.login_selection, name='mobile_login_selection'),
    path('login-selection', auth.login_selection, name='mobile_login_selection'),
    
    # Owner Login
    path('owner/login', auth.owner_login_view, name='mobile_owner_login'),
    
    # Employee Login
    path('employee/login', auth.employee_login_view, name='mobile_employee_login'),
    
    # Customer Login
    path('customer/login', auth.customer_login_view, name='mobile_customer_login'),
    
    # Legacy Routes (kept for compatibility)
    path('login', auth.login_view, name='mlogin_view'),
    path('logout', auth.logout_view, name='mlogout_view'),
    path('find-user', auth.find_user_view, name='mfind_user_view'),
    path('forgot-password', auth.forgot_password_view, name='mforgot_password_view'),
    
    # ================= Owner Dashboard URLs =================
    path('owner/dashboard', dashboard.owner_dashboard, name='mobile_owner_dashboard'),
    path('owner/sales-report', dashboard.owner_sales_report, name='mobile_owner_sales_report'),
    path('owner/inventory', dashboard.owner_inventory_status, name='mobile_owner_inventory'),
    
    # ================= Employee Dashboard URLs =================
    path('employee/dashboard', dashboard.employee_dashboard, name='mobile_employee_dashboard'),
    path('employee/create-invoice', dashboard.employee_create_invoice, name='mobile_employee_create_invoice'),
    
    # ================= Customer Dashboard URLs =================
    path('customer/dashboard', dashboard.customer_dashboard, name='mobile_customer_dashboard'),
    path('customer/invoices', dashboard.customer_invoices, name='mobile_customer_invoices'),
    path('customer/invoices/<int:invoice_id>', dashboard.customer_invoice_detail, name='mobile_customer_invoice_detail'),
    path('customer/ledger', dashboard.customer_ledger, name='mobile_customer_ledger'),
]