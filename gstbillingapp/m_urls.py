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
    path('order/cart', o.cart, name='m_order_cart'),
    path('order/checkout', o.order_checkout, name='m_order_checkout'),
    path('order/<int:quotation_id>', o.order_detail, name='m_order_detail'),
    path('order/<int:quotation_id>/update', o.order_update, name='m_order_update'),
    path('order/<int:quotation_id>/confirm', o.order_confirm, name='m_order_confirm'),
    path('order/<int:quotation_id>/cancel', o.order_cancel, name='m_order_cancel'),

    # ---- Customer ----
    path('customer/', c.home, name='m_customer_home'),
    path('customer/books', c.books, name='m_customer_books'),
    path('customer/invoices', c.invoices, name='m_customer_invoices'),
    path('customer/invoices/data', c.invoices_data, name='m_customer_invoices_data'),
    path('customer/books/data', c.books_data, name='m_customer_books_data'),
    path('customer/invoice/<int:invoice_id>', c.invoice_detail, name='m_customer_invoice'),
    path('customer/orders', c.orders, name='m_customer_orders'),
    path('customer/profile', c.profile, name='m_customer_profile'),

    # ---- Employee / field-staff ----
    path('employee/', e.home, name='m_employee_home'),
    path('employee/customers', e.customers, name='m_employee_customers'),
    path('employee/customer/<int:customer_id>', e.customer_detail, name='m_employee_customer'),
    path('employee/customer/<int:customer_id>/pay', e.record_payment, name='m_employee_record_payment'),
    path('employee/customer/<int:customer_id>/ledger', e.customer_ledger_data, name='m_employee_customer_ledger'),
    path('employee/customer/<int:customer_id>/map', e.customer_map, name='m_employee_customer_map'),
    path('employee/customer/<int:customer_id>/location', e.customer_set_location, name='m_employee_customer_set_location'),
    path('employee/invoices', e.invoices, name='m_employee_invoices'),
    path('employee/invoices/data', e.invoices_data, name='m_employee_invoices_data'),
    path('employee/invoice/<int:invoice_id>', e.invoice_detail, name='m_employee_invoice'),
    path('employee/collections', e.collections, name='m_employee_collections'),
    path('employee/collections/route', e.collections_route, name='m_employee_collections_route'),
    path('employee/orders', e.orders, name='m_employee_orders'),
    path('employee/pay', e.my_pay, name='m_employee_pay'),
    path('employee/approvals', e.approvals, name='m_employee_approvals'),
    path('employee/approvals/<int:log_id>/act', e.approval_act, name='m_employee_approval_act'),
]
