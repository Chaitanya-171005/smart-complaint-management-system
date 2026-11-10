from django.urls import path

from . import anonymous_views, tracking_views, views

app_name = "complaints"

urlpatterns = [
    path("track/", tracking_views.track_reference, name="track_reference"),
    path("anonymous/", anonymous_views.anonymous_submission, name="anonymous_submit"),
    path("new/", views.submit_complaint, name="submit"),
    path("<str:complaint_id>/submitted/", views.acknowledgement, name="acknowledgement"),
    path("evidence/<int:pk>/", views.download_evidence, name="download_evidence"),
]
