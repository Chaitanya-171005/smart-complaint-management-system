"""B11/B12 real persistence/HTTP/privacy tests with synthetic campus data."""

import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from PIL import Image, PngImagePlugin
from pypdf import PdfReader, PdfWriter

from accounts import permissions
from accounts.models import Location, SecurityEvent, User
from complaints import anonymous, anonymous_views, submission
from complaints.checks import anonymous_release_ready, check_anonymous_privacy
from complaints.evidence import PrivateEvidenceStorage
from complaints.intake import IdempotencyConflict, new_intake_key
from complaints.models import AnonymousIntakeReceipt, Attachment, Complaint, ComplaintIdSequence, IntakeReceipt
from complaints.privacy import anonymous_summary, complainant_label, private_evidence
from complaints.privacy_middleware import AnonymousExceptionReporter, AnonymousPrivacyMiddleware
from complaints.references import hash_reference
from routing.models import Category, RoutingDecision, SLAConfiguration
from workflow.models import ComplaintHistory
from workflow.services import get_owned_complaints

pytestmark = pytest.mark.django_db(transaction=True)
SECRET = "private-person@example.test"


def upload(name="private-person@example.test.png", kind="PNG"):
    stream = BytesIO()
    image = Image.new("RGB", (3, 3), "red")
    if kind == "PNG":
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Author", SECRET)
        image.save(stream, format=kind, pnginfo=meta)
    else:
        exif = Image.Exif()
        exif[315] = SECRET
        image.save(stream, format=kind, exif=exif)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/" + kind.lower())


def pdf_upload():
    stream = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Author": SECRET, "/Title": SECRET})
    writer.add_attachment("private.txt", SECRET.encode())
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
    annotation = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/T"): TextStringObject(SECRET),
    }))
    page[NameObject("/Annots")] = ArrayObject([annotation])
    writer.write(stream)
    writer.close()
    return SimpleUploadedFile("private-person@example.test.pdf", stream.getvalue(), content_type="application/pdf")


@pytest.fixture
def setup(routing_configuration, settings):
    settings.ANONYMOUS_TRANSPORT_VERIFIED = True
    settings.SECURE_HSTS_SECONDS = 300
    settings.SCMS_HTTPS_MODE = "direct"
    settings.SECURE_PROXY_SSL_HEADER = None
    settings.SECURE_SSL_REDIRECT = True
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.ANONYMOUS_INTAKE_ENABLED = True
    settings.ANONYMOUS_PRIVACY_READY = True
    settings.COMPLAINT_EMERGENCY_NOTICE = "SYNTHETIC TEST emergency notice, not campus policy."
    return {"key": new_intake_key(), "config": routing_configuration, "data": {
        "category": str(routing_configuration["category"].pk),
        "location": routing_configuration["location"].code,
        "title": "Synthetic anonymous light problem",
        "description": "The light in this synthetic room is not working correctly.",
        "sub_category": "", "priority": "LOW",
    }}


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"


def args(setup):
    return {key: setup[key] for key in ("key", "data")}


def paths(settings):
    return set(settings.PRIVATE_EVIDENCE_ROOT.glob("*"))


def empty(settings):
    for model in (Complaint, Attachment, AnonymousIntakeReceipt, IntakeReceipt,
                  RoutingDecision, ComplaintHistory, ComplaintIdSequence):
        assert not model.objects.exists(), model.__name__
    assert not paths(settings)


def token(client):
    response = client.get(reverse("complaints:anonymous_submit"), secure=True)
    assert response.status_code == 200
    return response.context["request_token"]


def post(setup, client, key=None, **overrides):
    return client.post(reverse("complaints:anonymous_submit"), {
        **setup["data"], "request_token": key or token(client), **overrides,
    }, secure=True, HTTP_ORIGIN="https://testserver")


def test_success_commits_anonymous_graph_without_any_account(setup, settings):
    with patch("complaints.models.secrets.token_hex", return_value="a" * 32) as random:
        result = anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    random.assert_called_once_with(16)
    assert result.reference == "a" * 32 and result.reference not in repr(result)
    assert not result.replayed and not connection.in_atomic_block
    complaint = Complaint.objects.get()
    receipt = AnonymousIntakeReceipt.objects.get()
    attachment = Attachment.objects.get()
    assert complaint.submitted_by_id is None and complaint.reference_digest == hash_reference(result.reference)
    assert complaint.status == "ASSIGNED" and complaint.department == setup["config"]["department"]
    assert complaint.routing_rule_key == str(setup["config"]["rule"].pk)
    assert complaint.due_at > complaint.submitted_at and complaint.complaint_id == result.complaint_id
    assert receipt.complaint == complaint and receipt.key_digest != setup["key"]
    assert attachment.uploaded_by_id is None and attachment.original_name == "evidence.png"
    assert not IntakeReceipt.objects.exists() and not User.objects.exists()
    assert not SecurityEvent.objects.exists()
    assert list(ComplaintHistory.objects.values_list("actor_kind", "new_state", "remarks")) == [
        ("ANONYMOUS", "SUBMITTED", ""), ("SYSTEM", "ASSIGNED", ""),
    ]
    for model in (Complaint, Attachment, AnonymousIntakeReceipt, RoutingDecision, ComplaintHistory):
        payload = json.dumps(list(model.objects.values()), default=str)
        assert result.reference not in payload and setup["key"] not in payload and SECRET not in payload
    assert len(paths(settings)) == 1


@pytest.mark.parametrize("file", [lambda: upload(), lambda: upload("private.jpg", "JPEG"), pdf_upload])
def test_file_metadata_names_and_embedded_attachments_removed(file):
    item, = private_evidence([file()])
    assert SECRET.encode() not in item.data
    assert item.original_name.startswith("evidence.")
    if item.content_type == "application/pdf":
        with PdfReader(BytesIO(item.data)) as reader:
            assert not reader.metadata and not reader.attachments
            assert "/Annots" not in reader.pages[0]
    else:
        with Image.open(BytesIO(item.data)) as image:
            assert not image.getexif() and "Author" not in image.info


def test_pdf_resource_metadata_is_removed_from_serialized_bytes():
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    metadata = DecodedStreamObject()
    metadata.set_data(("<xmp:Author>" + SECRET + "</xmp:Author>").encode())
    resource = DecodedStreamObject()
    resource.set_data(b"q Q")
    resource[NameObject("/Metadata")] = writer._add_object(metadata)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Fm0"): writer._add_object(resource)}),
    })
    stream = BytesIO()
    writer.write(stream)
    writer.close()
    cleaned, = private_evidence([SimpleUploadedFile("input.pdf", stream.getvalue(), content_type="application/pdf")])
    assert SECRET.encode() not in cleaned.data


@pytest.mark.parametrize("file", [lambda: upload(), pdf_upload])
def test_identical_retry_returns_no_reference_or_duplicate_files(setup, settings, file):
    first = anonymous.submit_anonymous_complaint(**args(setup), files=[file()])
    originals = paths(settings)
    replay = anonymous.submit_anonymous_complaint(**args(setup), files=[file()])
    assert replay.replayed and replay.reference is None and replay.complaint_id == first.complaint_id
    assert paths(settings) == originals and ComplaintIdSequence.objects.get().last_value == 1
    assert Complaint.objects.count() == AnonymousIntakeReceipt.objects.count() == Attachment.objects.count() == 1


def test_retry_survives_reference_and_sla_changes(setup):
    first = anonymous.submit_anonymous_complaint(**args(setup))
    Category.objects.update(active=False)
    Location.objects.update(active=False)
    SLAConfiguration.objects.update(active=False)
    replay = anonymous.submit_anonymous_complaint(**args(setup))
    assert replay.complaint_id == first.complaint_id and replay.reference is None


def test_changed_retry_conflicts_and_preserves_original(setup, settings):
    first = anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    originals = paths(settings)
    with pytest.raises(IdempotencyConflict):
        anonymous.submit_anonymous_complaint(**{**args(setup), "data": {**setup["data"], "title": "Changed"}}, files=[upload()])
    assert paths(settings) == originals and Complaint.objects.get().complaint_id == first.complaint_id


@pytest.mark.parametrize("failure", ["routing", "sla", "history", "attachment", "receipt", "commit", "storage"])
def test_required_failure_rolls_back_everything_without_private_diagnostics(setup, settings, failure):
    error = RuntimeError(SECRET)
    target = {
        "routing": (submission, "route_and_prioritize"),
        "sla": (None, "routing.intake.derive_priority_and_due"),
        "history": (submission, "record_history"),
        "attachment": (Attachment.objects, "create"),
        "receipt": (AnonymousIntakeReceipt.objects, "create"),
        "commit": (connection, "commit"),
        "storage": (PrivateEvidenceStorage, "save"),
    }[failure]
    if failure == "commit":
        error = IntegrityError(SECRET)
    guard = (patch(target[1], side_effect=error) if target[0] is None
             else patch.object(target[0], target[1], side_effect=error))
    with guard, pytest.raises(anonymous.AnonymousIntakeUnavailable) as caught:
        anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    assert SECRET not in str(caught.value)
    empty(settings)


def test_failure_can_retry_same_form_successfully(setup, settings):
    with patch.object(submission, "record_history", side_effect=OSError(SECRET)):
        with pytest.raises(anonymous.AnonymousIntakeUnavailable):
            anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    empty(settings)
    assert anonymous.submit_anonymous_complaint(**args(setup), files=[upload()]).reference


@pytest.mark.parametrize("key", [None, "", "x", "A" * 64, "g" * 64])
def test_invalid_operation_key_refused_before_storage(setup, settings, key):
    with pytest.raises(ValidationError):
        anonymous.submit_anonymous_complaint(**{**args(setup), "key": key}, files=[upload()])
    empty(settings)


@pytest.mark.parametrize("field,value", [("description", "short"), ("title", ""), ("priority", "ADMIN"),
                                         ("category", "0"), ("location", "bad/code"), ("email", SECRET)])
def test_shared_input_rules_and_extra_identity_fields_refused_in_service(setup, settings, field, value):
    with pytest.raises(ValidationError):
        anonymous.submit_anonymous_complaint(**{**args(setup), "data": {**setup["data"], field: value}})
    empty(settings)


def test_no_identity_or_source_argument_can_be_supplied(setup, settings):
    for name in ("user", "email", "ip_address", "session", "source_key"):
        with pytest.raises(TypeError):
            anonymous.submit_anonymous_complaint(**args(setup), **{name: SECRET})
    names = {field.name for field in AnonymousIntakeReceipt._meta.fields}
    assert names == {"id", "key_digest", "payload_digest", "complaint", "created_at"}
    empty(settings)


def test_outer_transaction_is_refused(setup, settings):
    with transaction.atomic(), pytest.raises(TransactionManagementError):
        anonymous.submit_anonymous_complaint(**args(setup))
    empty(settings)


def test_concurrent_double_submit_issues_one_reference_and_one_graph(setup, settings):
    barrier = threading.Barrier(2)
    def operation(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(operation, range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert sum(result.reference is not None for result in results) == 1
    assert len({result.complaint_id for result in results}) == 1 and len(paths(settings)) == 1
    assert Complaint.objects.count() == AnonymousIntakeReceipt.objects.count() == RoutingDecision.objects.count() == 1
    assert ComplaintHistory.objects.count() == 2


def test_http_has_no_login_requirement_and_displays_reference_only_on_first_post(setup, client):
    key = token(client)
    response = post(setup, client, key, evidence=upload())
    assert response.status_code == 200 and "Location" not in response.headers
    reference = response.context["reference"]
    assert re.fullmatch("[0-9a-f]{32}", reference) and reference.encode() in response.content
    assert b"cannot be recovered" in response.content and key.encode() not in response.content
    replay = post(setup, client, key, evidence=upload())
    assert replay.status_code == 200 and replay.context["reference"] is None
    assert reference.encode() not in replay.content and b"already accepted" in replay.content
    assert reference.encode() not in client.get(reverse("complaints:anonymous_submit"), secure=True).content
    assert all(reference not in str(cookie) for cookie in client.cookies.values())
    assert not Session.objects.exists()


def test_csrf_enforcement_is_preserved(setup, settings):
    client = Client(enforce_csrf_checks=True)
    key = token(client)
    assert post(setup, client, key).status_code == 403
    empty(settings)
    assert post(setup, client, key, csrfmiddlewaretoken=client.cookies["csrftoken"].value).status_code == 200


def test_logged_in_submitter_and_forged_identity_are_not_attached(setup, client, user_factory):
    user = user_factory(email=SECRET, full_name="Private identity")
    client.force_login(user)
    old_sessions = list(Session.objects.values())
    response = post(setup, client, email=user.email, submitted_by=str(user.pk),
                    name=user.full_name, reference="b" * 32, ip="198.51.100.18", evidence=upload())
    assert response.status_code == 200
    complaint = Complaint.objects.get()
    assert complaint.submitted_by_id is None and Attachment.objects.get().uploaded_by_id is None
    assert list(Session.objects.values()) == old_sessions
    assert response.wsgi_request.user.is_anonymous
    assert "sessionid" not in response.cookies
    assert SECRET.encode() not in response.content and b"Private identity" not in response.content
    assert client.get(reverse("accounts:landing_complainant"), secure=True).status_code == 200


@pytest.mark.parametrize("flag,value", [("COMPLAINT_INTAKE_ENABLED", False), ("ANONYMOUS_INTAKE_ENABLED", False),
                                       ("ANONYMOUS_PRIVACY_READY", False), ("COMPLAINT_EMERGENCY_NOTICE", ""),
                                       ("DEBUG", True), ("CSRF_USE_SESSIONS", True)])
def test_release_gates_block_get_and_post(setup, client, settings, flag, value):
    setattr(settings, flag, value)
    url = reverse("complaints:anonymous_submit")
    assert client.get(url, secure=True).status_code == client.post(url, setup["data"], secure=True).status_code == 503
    empty(settings)


def test_deployment_check_requires_privacy_release_gates(setup, settings):
    assert check_anonymous_privacy(None) == []
    settings.ANONYMOUS_PRIVACY_READY = False
    assert [error.id for error in check_anonymous_privacy(None)] == ["complaints.E002"]
    settings.ANONYMOUS_INTAKE_ENABLED = False
    assert check_anonymous_privacy(None) == []


def test_missing_privacy_middleware_fails_closed(setup, client, settings):
    settings.MIDDLEWARE = [path for path in settings.MIDDLEWARE if "AnonymousPrivacy" not in path]
    assert Client().post(reverse("complaints:anonymous_submit"), setup["data"], secure=True).status_code == 503
    empty(settings)


def test_privacy_middleware_after_session_middleware_fails_closed(setup, settings):
    path = "complaints.privacy_middleware.AnonymousPrivacyMiddleware"
    settings.MIDDLEWARE = [entry for entry in settings.MIDDLEWARE if entry != path] + [path]
    assert Client().post(reverse("complaints:anonymous_submit"), setup["data"], secure=True).status_code == 503
    empty(settings)


@pytest.mark.parametrize("value", ["", "bad", "x" * 1001])
def test_missing_or_forged_token_refused(setup, client, settings, value):
    assert client.post(reverse("complaints:anonymous_submit"), {**setup["data"], "request_token": value}, secure=True).status_code == 400
    empty(settings)


def test_authenticated_flow_token_cannot_be_used_for_anonymous_intake(setup, client, settings):
    bad = signing.dumps({"key": setup["key"], "user": 1}, salt="complaints.authenticated-intake")
    assert post(setup, client, bad).status_code == 400
    empty(settings)


def test_validation_errors_preserve_safe_fields_and_same_form(setup, client, settings):
    key = token(client)
    response = post(setup, client, key, description="short", title="<script>alert(1)</script>")
    assert response.status_code == 400 and response.context["request_token"] == key
    assert "description" in response.context["form"].errors
    assert b"<script>" not in response.content and b"&lt;script&gt;" in response.content
    empty(settings)
    assert post(setup, client, key).status_code == 200


@pytest.mark.parametrize("files", [lambda: [upload() for _ in range(4)],
                                   lambda: [SimpleUploadedFile("bad.png", b"invalid")]])
def test_invalid_batch_never_accepts(setup, client, settings, files):
    assert post(setup, client, evidence=files()).status_code == 400
    empty(settings)


def test_http_conflict_never_creates_another_complaint(setup, client):
    key = token(client)
    assert post(setup, client, key).status_code == 200
    response = post(setup, client, key, title="Different submission")
    assert response.status_code == 409 and "reference" not in response.context
    assert response.context["request_token"] == "" and key.encode() not in response.content
    assert b"Reload the anonymous form" in response.content and b"disabled" in response.content
    assert Complaint.objects.count() == 1


def test_http_failure_does_not_log_private_values_or_accept(setup, client, settings, caplog):
    with patch.object(submission, "record_history", side_effect=RuntimeError(SECRET)):
        response = post(setup, client, evidence=upload())
    assert response.status_code == 503 and "reference" not in response.context
    assert SECRET not in caplog.text and SECRET.encode() not in response.content
    empty(settings)


def test_cleanup_failure_logging_is_generic(setup, settings, caplog):
    with patch.object(submission, "record_history", side_effect=RuntimeError(SECRET)), \
         patch.object(PrivateEvidenceStorage, "delete", side_effect=OSError(SECRET)):
        with pytest.raises(anonymous.AnonymousIntakeUnavailable):
            anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    assert "Anonymous evidence rollback cleanup failed" in caplog.text
    assert SECRET not in caplog.text and not Complaint.objects.exists()
    # The intentionally undeletable file is isolated in tmp_path; production
    # cleanup reconciliation remains a deployment/recovery acceptance check.


def test_cookie_ip_headers_query_and_error_report_are_isolated(setup):
    request = RequestFactory().post("/anonymous/new/?email=" + SECRET, {
        "title": SECRET, "request_token": "c" * 64,
    }, REMOTE_ADDR="198.51.100.18", HTTP_X_FORWARDED_FOR="198.51.100.18",
        HTTP_USER_AGENT=SECRET, HTTP_AUTHORIZATION=SECRET,
        HTTP_COOKIE="sessionid=private-session; csrftoken=" + "a" * 32)
    middleware = AnonymousPrivacyMiddleware(lambda request: HttpResponse("ok"))
    response = middleware(request)
    assert request.COOKIES == {"csrftoken": "a" * 32} and not request.GET
    assert "REMOTE_ADDR" not in request.META and "HTTP_X_FORWARDED_FOR" not in request.META
    assert "HTTP_AUTHORIZATION" not in request.META and "HTTP_USER_AGENT" not in request.META
    request.user = AnonymousUser()
    try:
        raise ValueError(SECRET)
    except ValueError:
        report = AnonymousExceptionReporter(request, *sys.exc_info()).get_traceback_text()
    for value in (SECRET, "198.51.100.18", "private-session", "c" * 64):
        assert value not in report
    assert "no-store" in response["Cache-Control"] and response["Referrer-Policy"] == "no-referrer"


def test_privacy_response_headers_and_no_get_recovery_route(setup, client):
    response = post(setup, client)
    reference = response.context["reference"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response["Cache-Control"] and "noarchive" in response["X-Robots-Tag"]
    assert "form-action 'self'" in response["Content-Security-Policy"]
    for path in (f"/anonymous/new/{reference}/", f"/complaints/reference/{reference}/",
                 f"/anonymous/new/recover/{reference}/"):
        assert client.get(path, secure=True).status_code == 404
    assert client.put(reverse("complaints:anonymous_submit"), data="{}", secure=True).status_code == 405


def test_anonymous_reference_or_id_never_grants_full_record_or_evidence(setup, client, user_factory):
    response = post(setup, client, evidence=upload())
    complaint = Complaint.objects.get()
    attachment = Attachment.objects.get()
    download = reverse("complaints:download_evidence", args=[attachment.pk])
    ack = reverse("complaints:acknowledgement", args=[complaint.complaint_id])
    assert client.get(download + "?reference=" + response.context["reference"], secure=True).status_code == 404
    client.force_login(user_factory())
    assert client.get(ack, secure=True).status_code == 404 and client.get(download, secure=True).status_code == 404
    assert not get_owned_complaints(client.get(ack, secure=True).wsgi_request.user, Complaint.objects.all()).exists()
    staff = user_factory(role=User.Role.STAFF, department=complaint.department)
    assert permissions.can_view_complaint(staff, complaint)
    assert complainant_label(complaint) == "Anonymous"
    summary = anonymous_summary(complaint)
    assert set(summary) == {"complaint_id", "complainant", "category", "location", "status", "priority", "is_escalated", "escalation_level"}
    assert not {"submitted_by", "reference_digest", "attachments", "title", "description"} & set(summary)


def test_projection_rejects_authenticated_record(complaint_factory):
    complaint = complaint_factory()
    assert complainant_label(complaint) == complaint.submitted_by.full_name
    with pytest.raises(ValueError):
        anonymous_summary(complaint)


def test_anonymous_submission_works_under_atomic_requests(setup, client):
    with patch.dict(connection.settings_dict, {"ATOMIC_REQUESTS": True}):
        assert post(setup, client).status_code == 200
    assert Complaint.objects.count() == 1


def test_cross_origin_post_is_refused(setup, settings):
    client = Client(enforce_csrf_checks=True)
    key = token(client)
    response = client.post(reverse("complaints:anonymous_submit"), {
        **setup["data"], "request_token": key, "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
    }, HTTP_ORIGIN="https://other.example.test", secure=True)
    assert response.status_code == 403
    empty(settings)


def test_active_reference_corruption_and_deactivation_reject_new_intake(setup, settings):
    Category.objects.filter(pk=setup["config"]["category"].pk).update(name="Bad\nlabel")
    with pytest.raises(ValidationError):
        anonymous.submit_anonymous_complaint(**args(setup), files=[upload()])
    empty(settings)
    Category.objects.filter(pk=setup["config"]["category"].pk).update(active=False)
    with pytest.raises(ValidationError):
        anonymous.submit_anonymous_complaint(**args(setup))
    empty(settings)


def test_reference_collision_never_accepts_another_complaint(setup, settings):
    with patch("complaints.models.secrets.token_hex", return_value="d" * 32):
        first = anonymous.submit_anonymous_complaint(**args(setup))
        with pytest.raises(ValidationError):
            anonymous.submit_anonymous_complaint(**{**args(setup), "key": new_intake_key()})
    assert Complaint.objects.count() == AnonymousIntakeReceipt.objects.count() == 1
    assert Complaint.objects.get().reference_digest == hash_reference(first.reference)
    assert ComplaintIdSequence.objects.get().last_value == 1


def test_receipt_unique_key_and_digest_formats_are_database_enforced(setup):
    anonymous.submit_anonymous_complaint(**args(setup))
    receipt = AnonymousIntakeReceipt.objects.get()
    for field, value in (("key_digest", "A" * 64), ("payload_digest", "g" * 64)):
        with pytest.raises(IntegrityError), transaction.atomic():
            AnonymousIntakeReceipt.objects.filter(pk=receipt.pk).update(**{field: value})
    second = anonymous.submit_anonymous_complaint(**{**args(setup), "key": new_intake_key()})
    with pytest.raises(IntegrityError), transaction.atomic():
        AnonymousIntakeReceipt.objects.filter(complaint__complaint_id=second.complaint_id).update(key_digest=receipt.key_digest)


def test_unexpected_http_exception_returns_generic_nonacceptance(setup, client, settings, caplog):
    with patch.object(anonymous_views, "submit_anonymous_complaint", side_effect=ValueError(SECRET)):
        response = post(setup, client)
    assert response.status_code == 500 and SECRET.encode() not in response.content
    assert SECRET not in caplog.text and "reference" not in response.content.decode().lower()
    empty(settings)


def test_http_transport_cannot_accept_anonymous_submission(setup, client, settings):
    url = reverse("complaints:anonymous_submit")
    assert client.get(url).status_code == client.post(url, setup["data"]).status_code == 301
    empty(settings)


def test_authorization_refusal_does_not_join_account_to_anonymous_complaint(setup, client, user_factory):
    post(setup, client, evidence=upload())
    complaint = Complaint.objects.get()
    attachment = Attachment.objects.get()
    user = user_factory(email=SECRET)
    client.force_login(user)
    response = client.get(reverse("complaints:download_evidence", args=[attachment.pk]), secure=True)
    assert response.status_code == 404
    event = SecurityEvent.objects.get(event_type="AUTHORIZATION_REFUSED")
    assert event.user == user and event.identifier == SECRET
    assert event.detail == "can_view_evidence anonymous complaint"
    assert complaint.complaint_id not in event.detail and f"Complaint#{complaint.pk}" not in event.detail


def test_failure_after_issuance_never_logs_or_exposes_reference(setup, client, caplog):
    key = token(client)
    reference = "e" * 32
    with patch("complaints.models.secrets.token_hex", return_value=reference), \
         patch.object(AnonymousIntakeReceipt.objects, "create", side_effect=RuntimeError(reference)):
        response = post(setup, client, key)
    assert response.status_code == 503
    assert reference not in response.content.decode() and reference not in caplog.text
    assert not Complaint.objects.exists() and not AnonymousIntakeReceipt.objects.exists()


@pytest.mark.parametrize("name,value", [
    ("ANONYMOUS_TRANSPORT_VERIFIED", False), ("SECURE_HSTS_SECONDS", 0),
    ("SCMS_HTTPS_MODE", ""), ("SCMS_HTTPS_MODE", "unknown"),
    ("SECURE_SSL_REDIRECT", False), ("CSRF_COOKIE_SECURE", False),
    ("SESSION_COOKIE_SECURE", False),
    ("SECURE_PROXY_SSL_HEADER", ("HTTP_X_FORWARDED_PROTO", "https")),
])
def test_anonymous_tls_release_settings_are_required(setup, settings, client, name, value):
    setattr(settings, name, value)
    assert not anonymous_release_ready()
    assert [error.id for error in check_anonymous_privacy(None)] == ["complaints.E002"]
    url = reverse("complaints:anonymous_submit")
    assert client.get(url, secure=True).status_code == 503
    assert client.post(url, setup["data"], secure=True).status_code == 503
    empty(settings)


def test_anonymous_tls_requires_security_middleware(setup, settings):
    settings.MIDDLEWARE = [entry for entry in settings.MIDDLEWARE
                           if entry != "django.middleware.security.SecurityMiddleware"]
    assert not anonymous_release_ready()
    assert [error.id for error in check_anonymous_privacy(None)] == ["complaints.E002"]


def test_trusted_tls_proxy_accepts_post_and_issues_secure_csrf_cookie(setup, settings):
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    client = Client(enforce_csrf_checks=True)
    url = reverse("complaints:anonymous_submit")
    form = client.get(url, HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="testserver")
    assert form.status_code == 200 and form.wsgi_request.is_secure()
    assert form.cookies[settings.CSRF_COOKIE_NAME]["secure"]
    response = client.post(url, {**setup["data"], "request_token": form.context["request_token"],
                                 "csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value},
                           HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="testserver", HTTP_ORIGIN="https://testserver")
    assert response.status_code == 200 and response.context["reference"]
    assert Complaint.objects.get().submitted_by_id is None and not Session.objects.exists()


@pytest.mark.parametrize("value", [None, "http", ""])
def test_missing_or_insecure_proxy_scheme_cannot_accept_intake(setup, settings, client, value):
    settings.SCMS_HTTPS_MODE = "proxy"
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    headers = {} if value is None else {"HTTP_X_FORWARDED_PROTO": value}
    response = client.post(reverse("complaints:anonymous_submit"), setup["data"], **headers)
    assert response.status_code == 301 and response.url.startswith("https://")
    empty(settings)


def test_direct_tls_mode_does_not_trust_a_client_forwarded_proto_header(setup, settings, client):
    assert anonymous_release_ready() and settings.SECURE_PROXY_SSL_HEADER is None
    response = client.post(reverse("complaints:anonymous_submit"), setup["data"],
                           HTTP_X_FORWARDED_PROTO="https")
    assert response.status_code == 301
    empty(settings)


@pytest.mark.parametrize("attribute", ["session", "user", "_cached_user"])
def test_preloaded_request_identity_is_rejected_even_with_first_middleware(setup, settings, attribute):
    request = RequestFactory().post("/anonymous/new/", setup["data"], secure=True)
    setattr(request, attribute, {} if attribute == "session" else AnonymousUser())
    assert anonymous_release_ready()
    response = AnonymousPrivacyMiddleware(anonymous_views.anonymous_submission)(request)
    assert response.status_code == 503 and not request.anonymous_privacy_isolated
    empty(settings)


def test_sad_route_and_login_link_preserve_authenticated_urls(setup, client):
    from django.urls import resolve
    assert reverse("complaints:anonymous_submit") == "/anonymous/new/"
    assert resolve("/anonymous/new/").view_name == "complaints:anonymous_submit"
    assert reverse("complaints:submit") == "/complaints/new/"
    assert reverse("complaints:acknowledgement", args=["SCMS-2026-00001"]) == "/complaints/SCMS-2026-00001/submitted/"
    assert reverse("complaints:download_evidence", args=[1]) == "/complaints/evidence/1/"
    login = client.get(reverse("accounts:login"), secure=True)
    assert b'href="/anonymous/new/"' in login.content
    for method in (client.get, client.post):
        assert method("/complaints/anonymous/", secure=True).status_code == 404


@pytest.mark.parametrize("outcome", ["form", "invalid", "accepted"])
def test_anonymous_csrf_cookie_is_session_lifetime_with_existing_persistent_cookie(setup, settings, outcome):
    client = Client(enforce_csrf_checks=True)
    # A prior signed-in page may have issued Django's default persistent cookie.
    login = client.get(reverse("accounts:login"), secure=True)
    assert login.cookies[settings.CSRF_COOKIE_NAME]["max-age"]
    form = client.get(reverse("complaints:anonymous_submit"), secure=True)
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
    response = form
    if outcome != "form":
        response = post(setup, client, form.context["request_token"],
                        csrfmiddlewaretoken=csrf,
                        **({"description": "short"} if outcome == "invalid" else {}))
        assert response.status_code == (400 if outcome == "invalid" else 200)
    cookie = response.cookies[settings.CSRF_COOKIE_NAME]
    assert cookie.value == csrf and cookie["secure"]
    assert not cookie["max-age"] and not cookie["expires"]
    assert "sessionid" not in response.cookies and not Session.objects.exists()


@pytest.fixture(scope="module")
def noisy_jpeg_bytes():
    from random import Random
    # At quality 85 this genuine noisy JPEG is <3 MB. Re-encoding at quality 95
    # without subsampling grows it beyond either proposed D02 limit.
    image = Image.frombytes("RGB", (1900, 1900), Random(71).randbytes(1900 * 1900 * 3))
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=85)
    return stream.getvalue()


@pytest.mark.parametrize("limit", [5_000_000, 5 * 1024 * 1024])
def test_near_limit_jpeg_growth_rejects_entire_batch_before_staging(setup, settings, noisy_jpeg_bytes, limit):
    from complaints.evidence import validate_evidence
    settings.EVIDENCE_MAX_BYTES = limit
    # JPEG parsers permit trailing bytes; padding makes the actual readable
    # upload exactly one byte below the boundary without changing its pixels.
    original = noisy_jpeg_bytes + b"\0" * (limit - 1 - len(noisy_jpeg_bytes))
    assert len(original) == limit - 1
    file = SimpleUploadedFile("near-limit.jpg", original, content_type="image/jpeg")
    assert validate_evidence([file])[0].data == original
    with pytest.raises(ValidationError) as caught:
        anonymous.submit_anonymous_complaint(**args(setup), files=[upload(), file])
    assert caught.value.code == "size"
    empty(settings)


@pytest.mark.parametrize("limit", [5_000_000, 5 * 1024 * 1024])
def test_near_limit_jpeg_that_fits_after_sanitizing_is_committed(setup, settings, limit):
    settings.EVIDENCE_MAX_BYTES = limit
    stream = BytesIO()
    Image.new("RGB", (1900, 1900), "red").save(stream, format="JPEG", quality=85)
    original = stream.getvalue()
    file = SimpleUploadedFile("private.jpg", original + b"\0" * (limit - 1 - len(original)),
                              content_type="image/jpeg")
    accepted = anonymous.submit_anonymous_complaint(**args(setup), files=[file])
    attachment = Attachment.objects.get()
    assert accepted.reference and attachment.original_name == "evidence.jpg"
    stored = (settings.PRIVATE_EVIDENCE_ROOT / attachment.storage_name).read_bytes()
    assert attachment.size == len(stored) < limit and attachment.sha256 == hashlib.sha256(stored).hexdigest()
    with Image.open(BytesIO(stored)) as image:
        assert not image.getexif() and image.size == (1900, 1900)


def test_verified_https_response_sets_hsts(setup, client):
    response = client.get(reverse("complaints:anonymous_submit"), secure=True)
    assert response.status_code == 200
    assert response["Strict-Transport-Security"] == "max-age=300"
