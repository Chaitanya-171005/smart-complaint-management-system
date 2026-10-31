"""Shared B09 validation, private storage and authorized download primitives.

No public file URL is provided. Attachment persistence and the production view
must be integrated with the future Complaint model; see docs/B09.md.
"""

import hashlib
import os
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from itertools import islice
from pathlib import PurePosixPath
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse, Http404
from PIL import Image
from pypdf import PdfReader

from accounts.permissions import authorize_or_404, can_view_evidence

MAX_FILES = 3
FORMATS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".png": "image/png", ".pdf": "application/pdf"}
STORAGE_KEY = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|pdf)\Z")


@dataclass(frozen=True)
class ValidatedEvidence:
    original_name: str
    content_type: str
    extension: str
    data: bytes


@dataclass(frozen=True)
class StoredEvidence:
    storage_name: str
    original_name: str
    content_type: str
    size: int
    sha256: str


def _read_bounded(upload, limit):
    """Measure bytes ourselves, ignore client size, and restore the cursor."""
    try:
        position = upload.tell()
        upload.seek(0)
        try:
            data = bytearray()
            while len(data) <= limit:
                chunk = upload.read(min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            return bytes(data)
        finally:
            upload.seek(position)
    except (OSError, ValueError, AttributeError, TypeError):
        raise ValidationError("Evidence could not be read. Please select the file again.",
                              code="unreadable") from None


def _inspect(data):
    """Parse actual content, never the client's MIME declaration."""
    if data.startswith(b"%PDF-"):
        reader = PdfReader(BytesIO(data), strict=True)
        try:
            if reader.is_encrypted or not reader.pages:
                raise ValueError("Unreadable or empty PDF")
            # Force page-tree traversal, not just a five-byte magic check.
            for page in reader.pages:
                _ = page.mediabox
        finally:
            reader.close()
        return ".pdf", "application/pdf"
    with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as image:
        # Bound decoded image work as well as compressed upload bytes.
        if image.width * image.height > settings.EVIDENCE_MAX_IMAGE_PIXELS:
            raise ValueError("Image dimensions exceed the processing limit")
        kind = image.format
        image.verify()
    # verify() checks structure; load() also forces a decode of the first frame.
    with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as image:
        image.load()
    return (".jpg", "image/jpeg") if kind == "JPEG" else (".png", "image/png")


def validate_evidence(files):
    """Return immutable byte snapshots, or reject the entire batch with a reason.

    files is the COMPLETE set for this operation, not a per-file invocation.
    Both proposed D02 byte conventions are supported; neither is called agreed.
    """
    limit = settings.EVIDENCE_MAX_BYTES
    if type(limit) is not int or limit not in (5_000_000, 5 * 1024 * 1024):
        raise ImproperlyConfigured("EVIDENCE_MAX_BYTES must be 5000000 or 5242880 (D02).")
    files = list(islice(files, MAX_FILES + 1))
    if len(files) > MAX_FILES:
        raise ValidationError("Attach at most 3 evidence files per operation.", code="too_many")
    validated = []
    for index, upload in enumerate(files, 1):
        name = getattr(upload, "name", "")
        if not isinstance(name, str):
            name = ""
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name or len(name) > 255 or any(
            unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") for char in name
        ):
            raise ValidationError(f"Evidence {index}: invalid filename.", code="filename")
        extension = PurePosixPath(name).suffix.lower()
        if extension not in FORMATS:
            raise ValidationError(f"Evidence {index}: use JPEG, PNG or PDF.", code="type")
        data = _read_bounded(upload, limit)
        if not data or len(data) > limit:
            raise ValidationError(
                f"Evidence {index}: select a non-empty file of at most {limit} bytes.", code="size"
            )
        try:
            actual_extension, content_type = _inspect(data)
        except Exception:
            # Parser failures are invalid input; never echo file bytes or parser
            # diagnostics (which may contain private document content) to users.
            raise ValidationError(
                f"Evidence {index}: invalid, damaged, encrypted or oversized-image content.",
                code="content",
            ) from None
        if FORMATS[extension] != content_type:
            raise ValidationError(f"Evidence {index}: extension does not match its content.",
                                  code="mismatch")
        validated.append(ValidatedEvidence(name, content_type, actual_extension, data))
    return tuple(validated)


class PrivateEvidenceStorage(FileSystemStorage):
    """Django storage with no URL; generated flat keys and restrictive permissions."""

    def __init__(self):
        super().__init__(location=settings.PRIVATE_EVIDENCE_ROOT,
                         file_permissions_mode=0o600, directory_permissions_mode=0o700)

    def url(self, name):
        raise NotImplementedError("Evidence is available only through an authorized download.")

    def get_alternative_name(self, file_root, file_ext):
        return uuid4().hex + file_ext

    def _save(self, name, content):
        # O_EXCL never overwrites an existing file. Clean a partially written
        # file on I/O failure before Django's save() can return its key.
        path = self.path(name)
        os.makedirs(self.location, mode=0o700, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as destination:
                for chunk in content.chunks():
                    destination.write(chunk)
        except BaseException:
            os.unlink(path)
            raise
        return name


@contextmanager
def staged_evidence(files):
    """Validate ALL files before storage; remove this batch if the operation fails.

    Put the caller's transaction.atomic() INSIDE this context, so a database
    commit failure propagates through it and removes the staged files too.
    This does not protect against process crashes; B10 needs orphan recovery.
    """
    validated = validate_evidence(files)
    storage = PrivateEvidenceStorage()
    stored = []
    try:
        for item in validated:
            name = storage.save(uuid4().hex + item.extension, ContentFile(item.data))
            stored.append(StoredEvidence(name, item.original_name, item.content_type,
                                         len(item.data), hashlib.sha256(item.data).hexdigest()))
        yield tuple(stored)
    except BaseException:
        # Attempt every cleanup, even if one deletion fails. Preserve the
        # operation's original exception; failed cleanup must be logged.
        import logging
        for item in stored:
            try:
                storage.delete(item.storage_name)
            except OSError:
                logging.getLogger(__name__).exception("Evidence rollback cleanup failed")
        raise


def evidence_download_response(*, user, attachment):
    """Stream a server-loaded attachment after authorizing its OWN parent.

    attachment is trusted persistent metadata with complaint, storage_name and
    content_type. NEVER construct it from request fields or accept a separate
    caller-selected complaint. The production metadata/view is still pending.
    """
    if attachment is None:
        raise Http404
    authorize_or_404(can_view_evidence, user, attachment.complaint)
    name = attachment.storage_name
    if not isinstance(name, str) or not STORAGE_KEY.fullmatch(name):
        raise Http404
    content_type = FORMATS[PurePosixPath(name).suffix]
    if content_type != attachment.content_type:
        raise Http404
    try:
        stream = PrivateEvidenceStorage().open(name, "rb")
    except FileNotFoundError:
        raise Http404 from None
    response = FileResponse(stream, as_attachment=True,
                            filename="evidence-" + name, content_type=content_type)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
