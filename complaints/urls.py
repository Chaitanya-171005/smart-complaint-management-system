from django.urls import path

from . import views

app_name = "complaints"

urlpatterns = [
    path("new/", views.submit_complaint, name="submit"),
    path("<str:complaint_id>/submitted/", views.acknowledgement, name="acknowledgement"),
    path("evidence/<int:pk>/", views.download_evidence, name="download_evidence"),
]
