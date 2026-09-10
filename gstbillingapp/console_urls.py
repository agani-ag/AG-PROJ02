"""Routes for the operator console — mounted at /console/ (see gstbilling/urls.py).

Kept out of gstbillingapp.urls (business, session auth) and m_urls (mobile, signed-token
auth): the console is the platform side of the product and carries its own session
identity, so it gets its own URL module too.
"""
from django.urls import path

from .views import console
from .views import console_customers as cc
from .views import console_settings

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
    path("business/<int:user_id>/customer-app", console.business_customer_app,
         name="console_business_customer_app"),

    # Shared customers: suggestions, Parties (one real shop owner), app logins.
    path("customers", cc.customers, name="console_customers"),
    path("customers/suggestion/<int:key>", cc.suggestion, name="console_suggestion"),
    path("customer/<int:customer_id>", cc.customer_detail, name="console_customer_detail"),
    path("party/new", cc.party_new, name="console_party_new"),
    path("party/<int:party_id>", cc.party_detail, name="console_party"),
    path("party/<int:party_id>/update", cc.party_update, name="console_party_update"),
    path("party/<int:party_id>/add", cc.party_add, name="console_party_add"),
    path("party/<int:party_id>/remove", cc.party_remove, name="console_party_remove"),
    path("party/<int:party_id>/merge", cc.party_merge, name="console_party_merge"),
    path("party/<int:party_id>/copy-location", cc.party_copy_location,
         name="console_party_copy_location"),
    path("party/<int:party_id>/delete", cc.party_delete, name="console_party_delete"),
    path("party/<int:party_id>/login/issue", cc.party_login_issue,
         name="console_party_login_issue"),
    path("party/<int:party_id>/login/reset", cc.party_login_reset,
         name="console_party_login_reset"),
    path("party/<int:party_id>/login/deactivate", cc.party_login_deactivate,
         name="console_party_login_deactivate"),
    path("party/<int:party_id>/login/sync", cc.party_login_sync,
         name="console_party_login_sync"),

    path("admins", console.admins, name="console_admins"),
    path("password", console.change_password, name="console_change_password"),
    path("settings", console_settings.syncup_settings, name="console_syncup"),
    path("settings/test", console_settings.syncup_test, name="console_syncup_test"),
]
