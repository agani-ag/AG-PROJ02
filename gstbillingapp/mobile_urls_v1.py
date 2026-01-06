# Django imports
from django.urls import path

# Local imports
from .views.mobile_v1 import (
    customer
)

urlpatterns = [
    # Authentication URLs
    path('customer', customer.customer, name='v1customer'),
    path('customer/invoices', customer.customer_invoices, name='v1customerinvoices'),
    path('customer/books', customer.customer_books, name='v1customerbooks'),
]