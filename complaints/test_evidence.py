"""B09 primitives; HTTP tests use a test-only adapter, not a live intake view."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.urls import path
from django.views.decorators.http import require_safe
from PIL import Image
from pypdf import PdfWriter

from accounts.models import SecurityEvent, User
from complaints import evidence


def image_bytes(kind="PNG"):
    stream = BytesIO()
    Image.new("RGB", (3, 3), "blue").save(stream, format=kind)
    return stream.getvalue()


def pdf_bytes(*, encrypted=False, empty=False):
    writer = PdfWriter()
    if not empty:
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("synthetic-password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def upload(name="photo.png", data=None, mime="image/png"):
    return SimpleUploadedFile(name, image_bytes() if data is None else data,
                              content_type=mime)


@pytest.fixture
def private_root(settings, tmp_path):
    root = tmp_path / "private"
    settings.PRIVATE_EVIDENCE_ROOT = root
    return root


@pytest.mark.parametrize("name,kind,mime", [
    ("photo.jpg", "JPEG", "image/jpeg"), ("photo.JPEG", "JPEG", "image/jpeg"),
    ("photo.PNG", "PNG", "image/png"), ("report.pdf", "PDF", "application/pdf"),
])
def test_actual_supported_content(name, kind, mime):
    data = pdf_bytes() if kind == "PDF" else image_bytes(kind)
    (item,) = evidence.validate_evidence([upload(name, data, "application/octet-stream")])
    assert item.content_type == mime
    assert item.data == data


@pytest.mark.parametrize("count", [0, 1, 3])
def test_optional_evidence_and_three_file_boundary(count):
    assert len(evidence.validate_evidence(upload() for _ in range(count))) == count


def test_four_files_rejected_before_reading(monkeypatch):
    monkeypatch.setattr(evidence, "_read_bounded", lambda *_: pytest.fail("read before count check"))
    with pytest.raises(ValidationError, match="at most 3"):
        evidence.validate_evidence(upload() for _ in range(4))


@pytest.mark.parametrize("name,data", [
    ("bad.png", b""), ("bad.png", b"<script>alert(1)</script>"),
    ("bad.pdf", b"%PDF-1.7\nnot a PDF\n%%EOF"),
    ("bad.jpg", image_bytes("JPEG")[:30]),
    ("bad.png", image_bytes()[:-15]),
    ("bad.pdf", pdf_bytes(encrypted=True)),
    ("bad.pdf", pdf_bytes(empty=True)),
    ("bad.png", image_bytes("GIF")),
])
def test_invalid_or_unverifiable_content_rejected(name, data):
    with pytest.raises(ValidationError):
        evidence.validate_evidence([upload(name, data)])


@pytest.mark.parametrize("name,data", [
    ("renamed.png", image_bytes("JPEG")),
    ("renamed.jpg", image_bytes()), ("renamed.png", pdf_bytes()),
    ("renamed.pdf", image_bytes()), ("program.exe", image_bytes()),
    ("image.svg", b"<svg/>"), ("photo.png.html", image_bytes()),
])
def test_extension_and_content_must_agree(name, data):
    with pytest.raises(ValidationError):
        evidence.validate_evidence([upload(name, data)])


def test_client_mime_does_not_determine_stored_type():
    (item,) = evidence.validate_evidence([upload(mime="text/html")])
    assert item.content_type == "image/png"


@pytest.mark.parametrize("limit", [5_000_000, 5 * 1024 * 1024])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_both_proposed_d02_exact_byte_boundaries(settings, limit, delta):
    settings.EVIDENCE_MAX_BYTES = limit
    # A valid PDF with legal trailing whitespace; no parser is mocked.
    raw = pdf_bytes()
    raw += b" " * (limit + delta - len(raw))
    file = upload("report.pdf", raw)
    file.size = 1  # Declared size cannot bypass measuring actual bytes.
    if delta > 0:
        with pytest.raises(ValidationError, match="at most"):
            evidence.validate_evidence([file])
    else:
        assert len(evidence.validate_evidence([file])[0].data) == limit + delta


def test_invalid_limit_fails_as_configuration_error(settings):
    settings.EVIDENCE_MAX_BYTES = 1
    with pytest.raises(ImproperlyConfigured):
        evidence.validate_evidence([])


def test_image_processing_limit_is_enforced(settings):
    settings.EVIDENCE_MAX_IMAGE_PIXELS = 8
    with pytest.raises(ValidationError, match="oversized-image"):
        evidence.validate_evidence([upload()])


@pytest.mark.parametrize("name", ["bad\u202e.png", "bad\n.png", "bad\u200b.png", "bad\u2028.png"])
def test_control_and_format_characters_in_name_rejected(name):
    file = upload()
    file._name = name
    with pytest.raises(ValidationError, match="filename"):
        evidence.validate_evidence([file])


def test_empty_name_rejected():
    file = upload()
    file._name = ""
    with pytest.raises(ValidationError, match="filename"):
        evidence.validate_evidence([file])


def test_cursor_restored_and_snapshot_not_changed_later():
    file = upload()
    file.seek(5)
    item = evidence.validate_evidence([file])[0]
    assert file.tell() == 5
    file.seek(0)
    file.write(b"NOT AN IMAGE")
    assert item.data == image_bytes()


def test_closed_stream_gives_validation_error():
    file = upload()
    file.close()
    with pytest.raises(ValidationError, match="could not be read"):
        evidence.validate_evidence([file])


def test_invalid_file_restores_cursor():
    file = upload(data=b"synthetic invalid content")
    file.seek(3)
    with pytest.raises(ValidationError):
        evidence.validate_evidence([file])
    assert file.tell() == 3


def test_generated_names_and_private_permissions(private_root):
    with evidence.staged_evidence([upload(), upload("../../photo.png")]) as stored:
        assert len({item.storage_name for item in stored}) == 2
        for item in stored:
            assert evidence.STORAGE_KEY.fullmatch(item.storage_name)
            path = private_root / item.storage_name
            assert path.read_bytes() == image_bytes()
            assert item.size == len(image_bytes())
            assert len(item.sha256) == 64
            assert path.stat().st_mode & 0o777 == 0o600
    assert private_root.stat().st_mode & 0o777 == 0o700
    assert len(list(private_root.iterdir())) == 2
    with pytest.raises(NotImplementedError):
        evidence.PrivateEvidenceStorage().url(stored[0].storage_name)


def test_invalid_second_file_writes_nothing(private_root):
    with pytest.raises(ValidationError):
        with evidence.staged_evidence([upload(), upload(data=b"broken")]):
            pytest.fail("invalid batch yielded")
    assert not private_root.exists()


def test_later_operation_failure_cleans_batch_only(private_root):
    with evidence.staged_evidence([upload()]) as previous:
        pass
    with pytest.raises(RuntimeError, match="routing failed"):
        with evidence.staged_evidence([upload(), upload()]) as stored:
            assert len(stored) == 2
            raise RuntimeError("routing failed")
    assert [path.name for path in private_root.iterdir()] == [previous[0].storage_name]


def test_second_storage_failure_cleans_first(private_root, monkeypatch):
    original = evidence.PrivateEvidenceStorage._save
    calls = []

    def fail_second(self, name, content):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("synthetic storage failure")
        return original(self, name, content)

    monkeypatch.setattr(evidence.PrivateEvidenceStorage, "_save", fail_second)
    with pytest.raises(OSError, match="storage failure"):
        with evidence.staged_evidence([upload(), upload()]):
            pytest.fail("failed batch yielded")
    assert not list(private_root.iterdir())


def test_partial_file_write_is_removed(private_root):
    class BrokenContent(ContentFile):
        def chunks(self, chunk_size=None):
            yield b"partial bytes"
            raise OSError("synthetic write failure")

    with pytest.raises(OSError, match="write failure"):
        evidence.PrivateEvidenceStorage().save("a" * 32 + ".png", BrokenContent(b""))
    assert not list(private_root.iterdir())


def test_cleanup_failure_is_logged_without_hiding_original(private_root, monkeypatch, caplog):
    original = evidence.PrivateEvidenceStorage.delete
    calls = []

    def fail_first(self, name):
        calls.append(name)
        if len(calls) == 1:
            raise OSError("synthetic delete failure")
        return original(self, name)

    monkeypatch.setattr(evidence.PrivateEvidenceStorage, "delete", fail_first)
    with pytest.raises(RuntimeError, match="original failure"):
        with evidence.staged_evidence([upload(), upload()]):
            raise RuntimeError("original failure")
    assert len(calls) == 2
    assert "rollback cleanup failed" in caplog.text
    assert len(list(private_root.iterdir())) == 1


def test_storage_collision_does_not_overwrite(private_root):
    storage = evidence.PrivateEvidenceStorage()
    first = storage.save("a" * 32 + ".png", ContentFile(b"first"))
    second = storage.save(first, ContentFile(b"second"))
    assert first != second and evidence.STORAGE_KEY.fullmatch(second)
    assert (private_root / first).read_bytes() == b"first"


def test_database_rollback_cleans_files(private_root, department_factory):
    from accounts.models import Department
    from django.db import transaction

    initial_count = Department.objects.count()
    with pytest.raises(RuntimeError):
        with evidence.staged_evidence([upload()]):
            with transaction.atomic():
                department_factory()
                raise RuntimeError("required intake operation failed")
    assert Department.objects.count() == initial_count
    assert not list(private_root.iterdir())


# Test-only persistence adapter: production has no Complaint/Attachment model yet.
_attachments = {}


@require_safe
def download_adapter(request, key):
    return evidence.evidence_download_response(user=request.user, attachment=_attachments.get(key))


urlpatterns = [path("evidence/<str:key>/", download_adapter)]


@pytest.fixture
def download_case(settings, private_root, user_factory, department_factory):
    settings.ROOT_URLCONF = __name__
    owner = user_factory()
    department = department_factory()
    complaint = SimpleNamespace(pk=1, submitted_by_id=owner.pk, department_id=department.pk,
                                assignee_id=None)
    with evidence.staged_evidence([upload()]) as stored:
        item = stored[0]
    attachment = SimpleNamespace(complaint=complaint, **vars(item))
    _attachments["known"] = attachment
    yield SimpleNamespace(owner=owner, department=department, complaint=complaint,
                          attachment=attachment, private_root=private_root)
    _attachments.clear()


def consume(response):
    try:
        return b"".join(response.streaming_content)
    finally:
        response.close()


@pytest.mark.parametrize("role", ["owner", User.Role.STAFF, User.Role.HEAD])
def test_authorized_downloads_stream_verified_file(client, download_case, user_factory, role):
    case = download_case
    user = case.owner if role == "owner" else user_factory(role=role, department=case.department)
    client.force_login(user)
    response = client.get("/evidence/known/")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Content-Disposition"].startswith("attachment;")
    assert "photo.png" not in response["Content-Disposition"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]
    assert response["Vary"] == "Cookie"
    assert "sandbox" in response["Content-Security-Policy"]
    assert consume(response) == image_bytes()


@pytest.mark.parametrize("kind", ["anonymous", "other-owner", "other-staff", "other-head", "admin", "inactive"])
def test_denied_downloads_match_missing_and_never_open_files(
    client, download_case, user_factory, department_factory, monkeypatch, kind
):
    case = download_case
    if kind != "anonymous":
        values = {}
        if kind in ("other-staff", "other-head"):
            values = {"role": User.Role.STAFF if kind == "other-staff" else User.Role.HEAD,
                      "department": department_factory()}
        elif kind == "admin":
            values = {"role": User.Role.ADMIN}
        user = case.owner if kind == "inactive" else user_factory(**values)
        client.force_login(user)
        if kind == "inactive":
            User.objects.filter(pk=user.pk).update(is_active=False)
    monkeypatch.setattr(evidence.PrivateEvidenceStorage, "open", lambda *_: pytest.fail("opened before permission"))
    denied = client.get("/evidence/known/?reference=synthetic-valid-reference")
    missing = client.get("/evidence/missing/")
    assert denied.status_code == missing.status_code == 404
    assert denied.content == missing.content


@pytest.mark.django_db(transaction=True)
def test_role_changes_apply_on_next_request(client, download_case):
    client.force_login(download_case.owner)
    assert consume(client.get("/evidence/known/")) == image_bytes()
    User.objects.filter(pk=download_case.owner.pk).update(role=User.Role.ADMIN)
    assert client.get("/evidence/known/").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_department_changes_apply_on_next_request(client, download_case, user_factory, department_factory):
    staff = user_factory(role=User.Role.STAFF, department=download_case.department)
    client.force_login(staff)
    assert consume(client.get("/evidence/known/")) == image_bytes()
    User.objects.filter(pk=staff.pk).update(department=department_factory())
    assert client.get("/evidence/known/").status_code == 404


def test_evidence_uses_its_own_parent(client, download_case, user_factory):
    client.force_login(download_case.owner)
    download_case.complaint.submitted_by_id = user_factory().pk
    assert client.get("/evidence/known/?complaint_id=1").status_code == 404


def test_refusal_is_audited(client, download_case):
    before = SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED).count()
    assert client.get("/evidence/known/").status_code == 404
    assert SecurityEvent.objects.filter(event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED).count() == before + 1


def test_test_adapter_refuses_post(client, download_case):
    client.force_login(download_case.owner)
    assert client.post("/evidence/known/").status_code == 405


def test_department_reader_can_read_anonymous_complaint(client, download_case, user_factory):
    download_case.complaint.submitted_by_id = None
    staff = user_factory(role=User.Role.STAFF, department=download_case.department)
    client.force_login(staff)
    response = client.get("/evidence/known/")
    assert response.status_code == 200
    assert consume(response) == image_bytes()


def test_anonymous_complaint_reference_never_grants_access(client, download_case):
    download_case.complaint.submitted_by_id = None
    assert client.get("/evidence/known/?reference=synthetic-valid-reference").status_code == 404
    client.force_login(download_case.owner)
    assert client.get("/evidence/known/?reference=synthetic-valid-reference").status_code == 404


@pytest.mark.parametrize("key", ["../secret", "/etc/passwd", "a" * 32 + ".html", "a" * 32 + ".png/../x"])
def test_unsafe_storage_keys_refused_before_open(download_case, monkeypatch, key):
    download_case.attachment.storage_name = key
    monkeypatch.setattr(evidence.PrivateEvidenceStorage, "open", lambda *_: pytest.fail("opened unsafe key"))
    with pytest.raises(Http404):
        evidence.evidence_download_response(user=download_case.owner, attachment=download_case.attachment)


def test_missing_private_file_returns_404(client, download_case):
    (download_case.private_root / download_case.attachment.storage_name).unlink()
    client.force_login(download_case.owner)
    assert client.get("/evidence/known/").status_code == 404


def test_invalid_mime_metadata_returns_404(client, download_case):
    download_case.attachment.content_type = "text/html"
    client.force_login(download_case.owner)
    assert client.get("/evidence/known/").status_code == 404


def test_no_production_public_file_route(client, settings, download_case):
    settings.ROOT_URLCONF = "scms.urls"
    settings.DEBUG = True
    for prefix in ("/media/", "/private-evidence/", "/evidence/"):
        response = client.get(prefix + download_case.attachment.storage_name)
        assert response.status_code == 404


def test_resolution_reuses_same_batch_and_permission_contract(download_case, user_factory):
    staff = user_factory(role=User.Role.STAFF, department=download_case.department)
    with evidence.staged_evidence([upload("resolution.pdf", pdf_bytes())]) as stored:
        attachment = SimpleNamespace(complaint=download_case.complaint, **vars(stored[0]))
    response = evidence.evidence_download_response(user=staff, attachment=attachment)
    assert response["Content-Type"] == "application/pdf"
    assert consume(response).startswith(b"%PDF-")
    # The F4 operation, not this read permission, must also require assigned Staff
    # and a valid lifecycle transition before saving resolution metadata.
