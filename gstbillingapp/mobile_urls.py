# Django imports
from django.urls import path, include

# Local imports
from .views.mobile import (
    auth
)

urlpatterns = [
    # Authentication URLs
    path('login', auth.login_view, name='mlogin_view'),
    path('logout', auth.logout_view, name='mlogout_view'),
    path('find-user', auth.find_user_view, name='mfind_user_view'),
    path('forgot-password', auth.forgot_password_view, name='mforgot_password_view'),
]