from django.urls import path

from . import views
from . import reopening_views

app_name = "workflow"

urlpatterns = [
    path("<str:complaint_id>/reject-resolution/", reopening_views.reject, name="reject_resolution"),
    path("<str:complaint_id>/confirm/", views.confirm, name="confirm"),
    path("", views.complaint_list, name="complaint_list"),
    path("<str:complaint_id>/work/", views.work_status, name="work_status"),
    path("<str:complaint_id>/progress/", views.progress, name="progress"),
    path("<str:complaint_id>/resolve/", views.resolve, name="resolve"),
    path("<str:complaint_id>/", views.complaint_detail, name="complaint_detail"),
]
