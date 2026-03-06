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
]
