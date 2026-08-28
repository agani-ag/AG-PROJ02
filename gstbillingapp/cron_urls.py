"""Routes for the HTTP-triggered maintenance endpoints — mounted at /cron/.

Deliberately outside gstbillingapp.urls (session auth) and m_urls (signed-token mobile
auth): these are called by an external cron service and carry their own shared-secret
gate. See cron_views for the suggested schedule.
"""
from django.urls import path

from . import cron_views

urlpatterns = [
    path("health", cron_views.health, name="cron_health"),
    path("backup", cron_views.backup, name="cron_backup"),
    path("cleanup", cron_views.cleanup, name="cron_cleanup"),
]
