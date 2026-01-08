# Django imports
from django.urls import path

# Local imports
from .views.mobile_v1 import (
    customer
)

urlpatterns = [
    # Customer URLs
    path('customer/profile', customer.customer_profile, name='v1customerprofile'),
    path('customer/home', customer.customer_home, name='v1customerhome'),
    path('customer/books', customer.customer_books, name='v1customerbooks'),
    path('customer/invoices', customer.customer_invoices, name='v1customerinvoices'),
    path('customer/invoice_viewer/<int:invoice_id>', customer.customer_invoice_viewer, name='v1customerinvoiceviewer'),
    
    # Employee URLs
    path('customers', customer.customers, name='v1customers'),
    path('invoices', customer.invoices, name='v1invoices'),
    path('books', customer.books, name='v1books'),
    path('expensestracker', customer.ExpensesTracker, name='v1expensestracker'),

    # API URLs
    path('customers/api', customer.customersapi, name='v1customersapi'),
]