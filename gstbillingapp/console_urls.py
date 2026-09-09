"""Routes for the operator console — mounted at /console/ (see gstbilling/urls.py).

Kept out of gstbillingapp.urls (business, session auth) and m_urls (mobile, signed-token
auth): the console is the platform side of the product and carries its own session
identity, so it gets its own URL module too.
"""
from django.urls import path

from .views import console

urlpatterns = [
    path("login", console.console_login, name="console_login"),
    path("logout", console.console_logout, name="console_logout"),

    path("", console.businesses, name="console_businesses"),
    path("business/new", console.business_new, name="console_business_new"),
    path("business/<int:user_id>", console.business_detail, name="console_business_detail"),
    path("business/<int:user_id>/active", console.business_toggle_active,
         name="console_business_toggle_active"),
    path("business/<int:user_id>/password", console.business_reset_password,
         name="console_business_reset_password"),
    path("business/<int:user_id>/purge", console.business_purge, name="console_business_purge"),

    path("customers", console.customers, name="console_customers"),
    path("customer/<int:customer_id>", console.customer_detail,
         name="console_customer_detail"),

    path("admins", console.admins, name="console_admins"),
    path("password", console.change_password, name="console_change_password"),
]
