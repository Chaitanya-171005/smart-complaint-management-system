"""HTTP acceptance tests with real persistence and explicitly synthetic D01 data."""

from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.models import Location, User
from complaints.intake import IntakeReconciliationRequired
from complaints.models import Attachment, Complaint
from complaints.models import ComplaintIdSequence, IntakeReceipt
from routing.models import Category, RoutingDecision, SLAConfiguration
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db(transaction=True)


def upload(name="synthetic.png"):
    stream = BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


@pytest.fixture
def setup(complainant_user, routing_configuration, settings, tmp_path, client):
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = "SYNTHETIC TEST emergency notice; not confirmed campus policy."
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    client.force_login(complainant_user)
    config = routing_configuration
    data = {"category": str(config["category"].pk), "location": config["location"].code,
            "title": "Synthetic faulty light", "description": "The light in this synthetic room does not turn on.",
            "sub_category": "", "priority": "LOW"}
    return {"user": complainant_user, "config": config, "data": data,
            "url": reverse("complaints:submit"), "client": client}


def token_for(setup, client=None):
    response = (client or setup["client"]).get(setup["url"])
    assert response.status_code == 200
    return response.context["request_token"]


def submit(setup, token=None, **overrides):
    data = {**setup["data"], "request_token": token or token_for(setup), **overrides}
    return setup["client"].post(setup["url"], data)


def assert_not_accepted(settings):
    for model in (Complaint, Attachment, IntakeReceipt, RoutingDecision, ComplaintHistory, ComplaintIdSequence):
        assert not model.objects.exists(), model.__name__
    assert not list(settings.PRIVATE_EVIDENCE_ROOT.glob("*"))


def test_page_requires_login_and_exposes_no_token_to_anonymous(setup):
    client = Client()
    response = client.get(setup["url"])
    assert response.status_code == 302 and "/accounts/login/" in response.url
    assert "request_token" not in response.url


@pytest.mark.parametrize("role", [User.Role.STAFF, User.Role.HEAD, User.Role.ADMIN])
def test_noncomplainant_cannot_open_or_submit(setup, user_factory, settings, role):
    setup["client"].force_login(user_factory(role=role, department=setup["config"]["department"]))
    assert setup["client"].get(setup["url"]).status_code == 403
    assert setup["client"].post(setup["url"], setup["data"]).status_code == 403
    assert_not_accepted(settings)


@pytest.mark.parametrize("enabled,notice", [(False, "Synthetic notice"), (True, ""), (True, "   ")])
def test_release_gate_fails_closed_without_accepting(setup, settings, enabled, notice):
    settings.COMPLAINT_INTAKE_ENABLED = enabled
    settings.COMPLAINT_EMERGENCY_NOTICE = notice
    assert setup["client"].get(setup["url"]).status_code == 503
    assert setup["client"].post(setup["url"], setup["data"]).status_code == 503
    assert_not_accepted(settings)


def test_get_uses_active_references_emergency_notice_and_private_headers(setup):
    response = setup["client"].get(setup["url"])
    text = response.content.decode()
    assert response.status_code == 200
    assert "SYNTHETIC TEST emergency notice" in text and "csrfmiddlewaretoken" in text
    assert setup["config"]["category"].name in text
    assert setup["config"]["location"].code in text
    assert "private" in response["Cache-Control"] and "no-store" in response["Cache-Control"]
    assert "Cookie" in response["Vary"]


def test_csrf_is_required_and_valid_post_commits_before_acknowledgement(setup, settings):
    client = Client(enforce_csrf_checks=True)
    client.force_login(setup["user"])
    token = token_for(setup, client)
    data = {**setup["data"], "request_token": token, "evidence": upload()}
    assert client.post(setup["url"], data).status_code == 403
    assert_not_accepted(settings)
    data["evidence"] = upload()
    response = client.post(setup["url"], data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
    assert response.status_code == 303 and not connection.in_atomic_block
    complaint = Complaint.objects.get()
    assert complaint.status == "ASSIGNED" and IntakeReceipt.objects.get().accepted_complaint == complaint
    assert RoutingDecision.objects.count() == Attachment.objects.count() == 1
    assert list(ComplaintHistory.objects.values_list("new_state", flat=True)) == ["SUBMITTED", "ASSIGNED"]
    acknowledgement = client.get(response.url)
    assert acknowledgement.status_code == 200
    assert complaint.complaint_id.encode() in acknowledgement.content
    assert token.encode() not in acknowledgement.content
    assert b'aria-live="polite"' in acknowledgement.content
    assert b'Copy Complaint ID' in acknowledgement.content
    assert b'navigator.clipboard.writeText' in acknowledgement.content


@pytest.mark.parametrize("field", ["category", "location", "title", "description", "priority"])
def test_missing_fields_preserve_safe_values_and_request_key(setup, settings, field):
    token = token_for(setup)
    response = submit(setup, token, **{field: ""})
    assert response.status_code == 400
    assert response.context["request_token"] == token
    assert field in response.context["form"].errors
    if field != "title":
        assert b"Synthetic faulty light" in response.content
    assert_not_accepted(settings)


def test_invalid_text_is_escaped_and_can_be_corrected_using_same_key(setup, settings):
    token = token_for(setup)
    response = submit(setup, token, description="short", title="<script>alert(1)</script>")
    assert response.status_code == 400
    assert b"<script>" not in response.content and b"&lt;script&gt;" in response.content
    assert response.context["request_token"] == token
    assert_not_accepted(settings)
    assert submit(setup, token).status_code == 303


@pytest.mark.parametrize("token", ["", "tampered", "a" * 1001])
def test_unsigned_missing_or_oversized_tokens_refused(setup, settings, token):
    response = setup["client"].post(setup["url"], {**setup["data"], "request_token": token})
    assert response.status_code == 400
    assert_not_accepted(settings)


def test_another_accounts_signed_key_is_refused(setup, user_factory, settings):
    token = token_for(setup)
    setup["client"].force_login(user_factory())
    response = submit(setup, token)
    assert response.status_code == 400
    assert_not_accepted(settings)


def test_timeout_replay_after_reference_and_sla_changes_returns_same_ack(setup, settings):
    token = token_for(setup)
    first = submit(setup, token, evidence=upload())
    assert first.status_code == 303
    paths = set(settings.PRIVATE_EVIDENCE_ROOT.iterdir())
    Category.objects.filter(pk=setup["config"]["category"].pk).update(active=False)
    Location.objects.filter(pk=setup["config"]["location"].pk).update(active=False)
    SLAConfiguration.objects.update(active=False)
    replay = submit(setup, token, evidence=upload())
    assert replay.status_code == 303 and replay.url == first.url
    assert Complaint.objects.count() == IntakeReceipt.objects.count() == Attachment.objects.count() == 1
    assert ComplaintHistory.objects.count() == 2
    assert set(settings.PRIVATE_EVIDENCE_ROOT.iterdir()) == paths


def test_changed_accepted_payload_is_conflict_not_another_complaint(setup):
    token = token_for(setup)
    assert submit(setup, token).status_code == 303
    response = submit(setup, token, title="Changed details")
    assert response.status_code == 409 and response.context["request_token"] == token
    assert Complaint.objects.count() == 1


@pytest.mark.parametrize("failure", ["routing", "sla"])
def test_real_configuration_failure_preserves_key_without_success(setup, settings, failure):
    token = token_for(setup)
    if failure == "routing":
        rule = setup["config"]["rule"]
        rule.active = False
        rule.save()
        department = setup["config"]["department"]
        department.active = False
        department.save()
    else:
        SLAConfiguration.objects.update(active=False)
    response = submit(setup, token, evidence=upload())
    assert response.status_code == 503 and response.context["request_token"] == token
    assert "Location" not in response.headers
    assert_not_accepted(settings)


@pytest.mark.parametrize("error,status", [
    (OperationalError("controlled db failure"), 503), (OSError("controlled storage failure"), 503),
    (IntakeReconciliationRequired("legacy"), 409),
    (ValidationError("inactive", code="inactive_reference"), 400),
])
def test_service_refusals_cannot_become_success_pages(setup, settings, error, status):
    token = token_for(setup)
    with patch("complaints.views.submit_authenticated_complaint", side_effect=error):
        response = submit(setup, token)
    assert response.status_code == status and response.context["request_token"] == token
    assert "Location" not in response.headers
    assert_not_accepted(settings)


def test_history_failure_never_returns_an_acknowledgement(setup, settings):
    token = token_for(setup)
    setup["client"].raise_request_exception = False
    with patch("complaints.submission.record_history", side_effect=RuntimeError("controlled failure")):
        response = submit(setup, token, evidence=upload())
    assert response.status_code == 500 and "Location" not in response.headers
    assert_not_accepted(settings)


@pytest.mark.parametrize("files", [lambda: [upload() for _ in range(4)],
                                   lambda: [SimpleUploadedFile("bad.png", b"not an image")]])
def test_entire_file_batch_is_validated_by_http_flow(setup, settings, files):
    response = submit(setup, evidence=files())
    assert response.status_code == 400
    assert response.context["evidence_errors"]
    message = response.context["evidence_errors"][0]
    assert message not in response.context["form"].non_field_errors()
    markup = response.content.decode()
    assert markup.count(message) == 1
    assert markup.index('id="id_evidence"') < markup.index('id="evidence-errors"') < markup.index('id="evidence-help"')
    assert_not_accepted(settings)


def test_derived_post_fields_are_never_persisted(setup):
    response = submit(setup, department="99999", status="CLOSED", submitted_by="99999", due_at="2099-01-01")
    assert response.status_code == 303
    complaint = Complaint.objects.get()
    assert complaint.department == setup["config"]["department"]
    assert complaint.submitted_by == setup["user"] and complaint.status == "ASSIGNED"


def test_acknowledgement_requires_owner_and_real_linked_receipt(setup, user_factory, complaint_factory):
    response = submit(setup)
    owner_ack = setup["client"].get(response.url)
    assert owner_ack.status_code == 200
    assert "no-store" in owner_ack["Cache-Control"]
    other = complaint_factory(submitted_by=setup["user"])
    assert setup["client"].get(reverse("complaints:acknowledgement", args=[other.complaint_id])).status_code == 404
    setup["client"].force_login(user_factory())
    assert setup["client"].get(response.url).status_code == 404


def test_download_get_head_and_permission_changes_use_real_parent(setup, user_factory):
    submit(setup, evidence=upload())
    attachment = Attachment.objects.get()
    url = reverse("complaints:download_evidence", args=[attachment.pk])
    response = setup["client"].get(url)
    assert response.status_code == 200 and b"".join(response.streaming_content)
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response["Content-Disposition"] and "no-store" in response["Cache-Control"]
    response.close()
    head = setup["client"].head(url)
    assert head.status_code == 200 and b"".join(head.streaming_content) == b""
    head.close()
    staff = user_factory(role=User.Role.STAFF, department=setup["config"]["department"])
    setup["client"].force_login(staff)
    response = setup["client"].get(url)
    assert response.status_code == 200
    response.close()
    User.objects.filter(pk=staff.pk).update(department=None)
    assert setup["client"].get(url).status_code == 404
    setup["client"].force_login(user_factory())
    assert setup["client"].get(url).status_code == 404
    setup["client"].logout()
    assert setup["client"].get(url).status_code == 404
    assert setup["client"].get("/private-evidence/" + attachment.storage_name).status_code == 404


def test_unsafe_methods_cannot_download_or_change_acknowledgements(setup):
    accepted = submit(setup, evidence=upload())
    url = reverse("complaints:download_evidence", args=[Attachment.objects.get().pk])
    assert setup["client"].post(url).status_code == 405
    assert setup["client"].post(accepted.url).status_code == 405
    assert setup["client"].put(setup["url"], data="{}").status_code == 405


def test_submission_works_with_atomic_requests_enabled(setup):
    token = token_for(setup)
    with patch.dict(connection.settings_dict, {"ATOMIC_REQUESTS": True}):
        assert submit(setup, token).status_code == 303
    assert Complaint.objects.count() == 1
