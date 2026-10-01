from django.apps import AppConfig


class GstbillingappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gstbillingapp'

    def ready(self):
        # Keeps every row pointed at the person holding its number (identity.py).
        from . import identity_hooks  # noqa: F401
        # Connects the hooks that queue SyncUp messages (bills, payments, orders).
        from . import syncup_messages  # noqa: F401
        # Connects the desktop sign-in hook that announces logins to Telegram.
        from . import telegram_alerts  # noqa: F401