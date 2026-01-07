# Django imports
from django.urls import path

# Local imports
from .views.mobile_v1 import (
    customer
)

urlpatterns = [
    # Authentication URLs
    path('customers', customer.customers, name='v1customers'),
    path('customer', customer.customer, name='v1customer'),
    path('customer/home', customer.customer_home, name='v1customerhome'),
    path('customer/books', customer.customer_books, name='v1customerbooks'),
    path('customer/invoices', customer.customer_invoices, name='v1customerinvoices'),
    path('customer/invoice_viewer/<int:invoice_id>', customer.customer_invoice_viewer, name='v1customerinvoiceviewer'),
]