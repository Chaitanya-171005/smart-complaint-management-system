from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("register/done/", views.register_done, name="register_done"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("home/", views.landing, name="home"),
    path("landing/complainant/", views.landing_complainant, name="landing_complainant"),
    path("landing/staff/", views.landing_staff, name="landing_staff"),
    path("landing/head/", views.landing_head, name="landing_head"),
    path("landing/admin/", views.landing_admin, name="landing_admin"),
]
