"""gstbilling URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include
from django.urls import path
from django.views.generic.base import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('gstbillingapp.urls')),
    path('m/', include('gstbillingapp.m_urls')),
    path('cron/', include('gstbillingapp.cron_urls')),   # external cron service (shared-secret)
    path('console/', include('gstbillingapp.console_urls')),  # operator console (own session auth)

    # Browsers (and link unfurlers) request /favicon.ico from the site root regardless of
    # the <link> tags, and static/ is not the web root — so point it at the real file.
    path('favicon.ico', RedirectView.as_view(
        url=static_url('gstbillingapp/images/favicon.ico'), permanent=True)),
]
