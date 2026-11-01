from django.urls import path

from . import admin_views, views

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
    path("admin-config/departments/", admin_views.departments, name="admin_departments"),
    path("admin-config/departments/<int:pk>/edit/", admin_views.department_edit, name="admin_department_edit"),
    path("admin-config/departments/<int:pk>/active/", admin_views.department_active, name="admin_department_active"),
    path("admin-config/users/", admin_views.users, name="admin_users"),
    path("admin-config/users/<int:pk>/edit/", admin_views.user_edit, name="admin_user_edit"),
    path("admin-config/locations/", admin_views.locations, name="admin_locations"),
    path("admin-config/locations/<int:pk>/edit/", admin_views.location_edit, name="admin_location_edit"),
    path("admin-config/locations/<int:pk>/active/", admin_views.location_active, name="admin_location_active"),
]
