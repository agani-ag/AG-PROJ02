from django.apps import AppConfig


class GstbillingappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gstbillingapp'

    def ready(self):
        # Connects the hook that switches off a deleted employee's SyncUp login.
        from . import staff  # noqa: F401