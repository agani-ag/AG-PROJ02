"""Routes for the operator console — mounted at /console/ (see gstbilling/urls.py).

Kept out of gstbillingapp.urls (business, session auth) and m_urls (mobile, signed-token
auth): the console is the platform side of the product and carries its own session
identity, so it gets its own URL module too.
"""
from django.urls import path

from .views import console
from .views import console_data as data
from .views import console_people as people
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
    path("business/<int:user_id>/passkey/generate", console.business_passkey_generate,
         name="console_business_passkey_generate"),
    path("business/<int:user_id>/passkey/set", console.business_passkey_set,
         name="console_business_passkey_set"),
    path("business/<int:user_id>/passkey/off", console.business_passkey_off,
         name="console_business_passkey_off"),
    path("business/<int:user_id>/messages", console.business_messages,
         name="console_business_messages"),
    path("business/<int:user_id>/confirm-balances", console.business_confirm_balances,
         name="console_business_confirm_balances"),
    path("business/<int:user_id>/telegram", console.business_telegram,
         name="console_business_telegram"),
    path("business/<int:user_id>/telegram/logins", console.business_telegram_logins,
         name="console_business_telegram_logins"),
    path("business/<int:user_id>/telegram/add", console.business_telegram_chat_add,
         name="console_business_telegram_chat_add"),
    path("business/<int:user_id>/telegram/reuse", console.business_telegram_chat_reuse,
         name="console_business_telegram_chat_reuse"),
    path("business/<int:user_id>/telegram/<int:chat_id>/toggle",
         console.business_telegram_chat_toggle, name="console_business_telegram_chat_toggle"),
    path("business/<int:user_id>/telegram/<int:chat_id>/delete",
         console.business_telegram_chat_delete, name="console_business_telegram_chat_delete"),
    path("business/<int:user_id>/telegram/<int:chat_id>/test",
         console.business_telegram_chat_test, name="console_business_telegram_chat_test"),

    # Looking at the people who use the app — read-only; nothing is issued here.
    path("customers", people.customers, name="console_customers"),
    path("customers/rows", people.rows, name="console_customer_rows"),
    path("employees", people.employees, name="console_employees"),
    path("people/problems", people.problems, name="console_problems"),
    path("person/<int:person_id>", people.person, name="console_person"),

    # The database itself. One screen: the table is ?t=, so the only paths are the grid and
    # a single row.
    path("data", data.browse, name="console_data"),
    path("data/new/<str:label>", data.add, name="console_data_add"),
    path("data/row/<str:label>/<str:pk>", data.row, name="console_data_row"),
    path("data/row/<str:label>/<str:pk>/delete", data.delete, name="console_data_delete"),

    path("admins", console.admins, name="console_admins"),
    path("password", console.change_password, name="console_change_password"),
    path("settings", console_settings.syncup_settings, name="console_syncup"),
    path("settings/test", console_settings.syncup_test, name="console_syncup_test"),
]
