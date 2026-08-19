"""
Mobile web (/m/) routes — lean responsive pages served into the SyncUp WebView.
Auth: signed token minted by gstbilling (mobile_auth.py), not legacy cid/users_filter.
"""
from django.urls import path

from .views.m import customer as c
from .views.m import employee as e
from .views.m import order as o

urlpatterns = [
    # ---- Order flow (customer self-order / employee order-for-customer) ----
    path('order', o.order, name='m_order'),
    path('order/checkout', o.order_checkout, name='m_order_checkout'),

    # ---- Customer ----
    path('customer/', c.home, name='m_customer_home'),
    path('customer/books', c.books, name='m_customer_books'),
    path('customer/invoices', c.invoices, name='m_customer_invoices'),
    path('customer/invoice/<int:invoice_id>', c.invoice_detail, name='m_customer_invoice'),
    path('customer/orders', c.orders, name='m_customer_orders'),
    path('customer/profile', c.profile, name='m_customer_profile'),

    # ---- Employee / field-staff ----
    path('employee/', e.home, name='m_employee_home'),
    path('employee/customers', e.customers, name='m_employee_customers'),
    path('employee/customer/<int:customer_id>', e.customer_detail, name='m_employee_customer'),
    path('employee/customer/<int:customer_id>/pay', e.record_payment, name='m_employee_record_payment'),
    path('employee/invoices', e.invoices, name='m_employee_invoices'),
    path('employee/collections', e.collections, name='m_employee_collections'),
    path('employee/orders', e.orders, name='m_employee_orders'),
]
