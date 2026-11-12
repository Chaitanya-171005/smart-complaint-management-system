from django.urls import path

from . import views

app_name = "routing"

urlpatterns = [
    path("queue/", views.queue, name="queue"),
    path("configuration/", views.configuration, name="configuration"),
]
