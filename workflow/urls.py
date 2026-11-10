from django.urls import path

from . import views

app_name = "workflow"

urlpatterns = [
    path("", views.complaint_list, name="complaint_list"),
    path("<str:complaint_id>/work/", views.work_status, name="work_status"),
    path("<str:complaint_id>/progress/", views.progress, name="progress"),
    path("<str:complaint_id>/resolve/", views.resolve, name="resolve"),
    path("<str:complaint_id>/", views.complaint_detail, name="complaint_detail"),
]
