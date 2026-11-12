from django.urls import path

from . import anonymous_views, views

app_name = "complaints"

urlpatterns = [
    path("anonymous/new/", anonymous_views.anonymous_submission, name="anonymous_submit"),
    path("complaints/new/", views.submit_complaint, name="submit"),
    path("complaints/<str:complaint_id>/submitted/", views.acknowledgement, name="acknowledgement"),
    path("complaints/evidence/<int:pk>/", views.download_evidence, name="download_evidence"),
]
