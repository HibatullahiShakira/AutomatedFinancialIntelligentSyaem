"""
Core app URL configuration.
"""
from django.urls import path
from apps.core import views

app_name = "core"

urlpatterns = [
    path("auth/register/", views.register, name="register"),
    path("auth/login/", views.login, name="login"),
    path("auth/refresh/", views.refresh_token, name="refresh_token"),
    path("auth/logout/", views.logout, name="logout"),
    path("auth/verify-email/", views.verify_email, name="verify_email"),
    path("auth/forgot-password/", views.forgot_password, name="forgot_password"),
    path("auth/reset-password/", views.reset_password, name="reset_password"),
    path("auth/totp/setup/", views.totp_setup, name="totp_setup"),
    path("auth/totp/verify/", views.totp_verify, name="totp_verify"),
    path("auth/totp/authenticate/", views.totp_authenticate, name="totp_authenticate"),
]
