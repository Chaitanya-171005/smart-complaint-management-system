"""B12 explicit output and metadata boundaries; no source-identity collection."""

from io import BytesIO

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from .evidence import validate_evidence


def _strip_pdf_metadata(root):
    # Walk resource dictionaries too: page-only removal misses XMP attached to
    # an embedded image/form. Track resolved objects to handle PDF graph cycles.
    pending, seen = [root], set()
    keys = {"/Metadata", "/PieceInfo", "/Annots", "/AF", "/EmbeddedFiles",
            "/AA", "/OpenAction", "/Author", "/Creator", "/Producer",
            "/CreationDate", "/ModDate", "/LastModified", "/Keywords", "/Subject"}
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, DictionaryObject):
            for key in keys.intersection(value):
                del value[key]
            pending.extend(value.values())
        elif isinstance(value, ArrayObject):
            pending.extend(value)


def complainant_label(complaint):
    """Never infer anonymous identity from an uploader, assignee or session."""
    if complaint.submitted_by_id is None:
        return "Anonymous"
    return complaint.submitted_by.full_name


def anonymous_summary(complaint):
    """Allowlisted context for anonymous displays/reports/staff notifications.

    Free text, evidence, the reference digest and account relations are omitted.
    It is a projection, not authorization; callers must authorize first.
    """
    if complaint.submitted_by_id is not None or not complaint.reference_digest:
        raise ValueError("Use an anonymous complaint.")
    return {
        "complaint_id": complaint.complaint_id, "complainant": "Anonymous",
        "category": complaint.category, "location": complaint.location_code,
        "status": complaint.status, "is_escalated": complaint.is_escalated,
        "escalation_level": complaint.escalation_level,
    }


def private_evidence(files):
    """Validate originals, remove automatic filename/metadata linkage, revalidate.

    Visible text/pixels may themselves identify the author: the form warns about
    this and cannot promise to anonymize user-authored document contents.
    """
    result = []
    for item in validate_evidence(files):
        output = BytesIO()
        try:
            if item.content_type == "application/pdf":
                with PdfReader(BytesIO(item.data), strict=True) as reader:
                    writer = PdfWriter()
                    writer.append_pages_from_reader(reader)
                    writer.metadata = None
                    _strip_pdf_metadata(writer.root_object)
                    # Deleted metadata/annotations may have been indirect
                    # objects. Remove unreachable copies from the output bytes.
                    writer.compress_identical_objects()
                    writer.write(output)
                    writer.close()
            else:
                with Image.open(BytesIO(item.data)) as original:
                    image = ImageOps.exif_transpose(original)
                    # Copy pixels into a fresh image; copying the source image
                    # object alone can retain EXIF, text chunks or ICC metadata.
                    mode = "RGBA" if item.content_type == "image/png" else "RGB"
                    pixels = image.convert(mode)
                    clean = Image.new(mode, pixels.size)
                    clean.paste(pixels)
                    if mode == "RGBA":
                        clean.save(output, format="PNG")
                    else:
                        clean.save(output, format="JPEG", quality=95, subsampling=0)
        except Exception:
            raise ValidationError("Evidence could not be prepared privately. Select another file.",
                                  code="private_evidence") from None
        sanitized = ContentFile(output.getvalue(), name="evidence" + item.extension)
        result.extend(validate_evidence([sanitized]))
    return tuple(result)
