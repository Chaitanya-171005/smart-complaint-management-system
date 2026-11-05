from django.urls import path

from . import views

app_name = "routing"

urlpatterns = [
    path("configuration/", views.configuration, name="configuration"),
]
