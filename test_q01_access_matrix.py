"""Q01 end-to-end access, escaping and anonymity checks across F1-F4 (TC-02, TC-04, TC-05, TC-13, VM-02).

Every check goes through the real URLs with a signed-in client, so it exercises permissions on the server
and not the page a role happens to see. test_q01_security_validation.py covers routes in general; this file
covers who may do what to one complaint, and what the pages show.
"""

from io import BytesIO

import pytest
from django.test import Client
from PIL import Image

from complaints.models import Attachment, Complaint
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db

XSS_TITLE = "<script>alert('t')</script>"
XSS_DESCRIPTION = 'The light is broken "><img src=x onerror=alert(1)> in this synthetic room.'
XSS_REMARKS = "<svg onload=alert(2)> fixed with synthetic remarks"
RAW_PAYLOADS = ("<script>alert('t')</script>", "<img src=x onerror=alert(1)>", "<svg onload=alert(2)>")


@pytest.fixture
def world(user_factory, department, department_factory, complaint_factory):
    """One complaint in `department`, owned by `owner`, plus a user of every kind around it."""
    other_department = department_factory()
    people = {
        "owner": user_factory(role="COMPLAINANT"),
        "other_complainant": user_factory(role="COMPLAINANT"),
        "staff": user_factory(role="STAFF", department=department),
        "head": user_factory(role="HEAD", department=department),
        "other_staff": user_factory(role="STAFF", department=other_department),
        "other_head": user_factory(role="HEAD", department=other_department),
        "admin": user_factory(role="ADMIN"),
    }
    complaint = complaint_factory(
        submitted_by=people["owner"], department=department, assignee=people["staff"],
        status=Complaint.Status.IN_PROGRESS, title=XSS_TITLE, description=XSS_DESCRIPTION,
        resolution_remarks=XSS_REMARKS,
    )
    return {"complaint": complaint, "department": department, "other_department": other_department, **people}


def client_for(user):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def same_as_missing(user, response, missing_path):
    """A refusal must look exactly like a missing record, so ids cannot be probed."""
    missing = client_for(user).get(missing_path)
    return response.status_code == missing.status_code


# --- who may read a complaint and its evidence (REQ-ACC-01, REQ-SEC-02/05) -------------------------------

READERS = {"owner", "staff", "head"}
OUTSIDERS = ["other_complainant", "other_staff", "other_head", "admin"]
# F4 gives the owner /complaints/<id>/ and department Staff/Head /complaints/<id>/work/.
READ_PATH = {"owner": "/complaints/{id}/", "staff": "/complaints/{id}/work/", "head": "/complaints/{id}/work/"}


@pytest.mark.parametrize("who", sorted(READERS))
def test_owner_and_own_department_may_read_the_complaint(world, who):
    path = READ_PATH[who].format(id=world["complaint"].complaint_id)
    assert client_for(world[who]).get(path).status_code == 200


@pytest.mark.parametrize("template", ["/complaints/{id}/", "/complaints/{id}/work/"])
@pytest.mark.parametrize("who", OUTSIDERS)
def test_everyone_else_gets_the_same_answer_as_for_a_missing_complaint(world, who, template):
    complaint = world["complaint"]
    response = client_for(world[who]).get(template.format(id=complaint.complaint_id))
    assert response.status_code in (403, 404)
    assert same_as_missing(world[who], response, template.format(id="SCMS-2026-999999"))
    assert complaint.title.encode() not in response.content


def test_staff_and_head_cannot_use_the_owners_pages(world):
    complaint = world["complaint"]
    for who in ("staff", "head"):
        assert client_for(world[who]).get(f"/complaints/{complaint.complaint_id}/").status_code in (403, 404)
        assert client_for(world[who]).get("/complaints/").status_code in (403, 404)


@pytest.mark.parametrize("template", ["/complaints/{id}/", "/complaints/{id}/work/"])
def test_signed_out_visitors_are_sent_to_sign_in(world, template):
    response = client_for(None).get(template.format(id=world["complaint"].complaint_id))
    assert response.status_code == 302 and "login" in response["Location"]


@pytest.fixture
def evidence(world, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    root = settings.PRIVATE_EVIDENCE_ROOT
    root.mkdir()
    stream = BytesIO()
    Image.new("RGB", (3, 3), "blue").save(stream, format="PNG")
    data = stream.getvalue()
    name = "a" * 32 + ".png"
    (root / name).write_bytes(data)
    import hashlib

    attachment = Attachment.objects.create(
        complaint=world["complaint"], storage_name=name, original_name="photo.png", content_type="image/png",
        size=len(data), sha256=hashlib.sha256(data).hexdigest(), stage=Attachment.Stage.INTAKE,
        uploaded_by=world["owner"],
    )
    return attachment, data


@pytest.mark.parametrize("who", sorted(READERS))
def test_evidence_downloads_follow_the_parent_complaint(world, evidence, who):
    attachment, data = evidence
    response = client_for(world[who]).get(f"/complaints/evidence/{attachment.pk}/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == data
    assert "private" in response["Cache-Control"] and "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response["Content-Disposition"]
    assert attachment.original_name not in response["Content-Disposition"]  # no user-chosen file name


@pytest.mark.parametrize("who", OUTSIDERS)
def test_evidence_is_refused_like_a_missing_file_to_everyone_else(world, evidence, who):
    attachment, _ = evidence
    response = client_for(world[who]).get(f"/complaints/evidence/{attachment.pk}/")
    assert response.status_code == 404
    assert same_as_missing(world[who], response, "/complaints/evidence/999999/")


def test_evidence_needs_sign_in_and_cannot_be_reached_by_path_or_query_tricks(world, evidence):
    attachment, _ = evidence
    assert client_for(None).get(f"/complaints/evidence/{attachment.pk}/").status_code in (302, 403, 404)
    client = client_for(world["other_complainant"])
    for path in (f"/complaints/evidence/{attachment.pk}/?complaint_id={world['complaint'].complaint_id}",
                 f"/complaints/evidence/{attachment.pk}/../", "/complaints/evidence/../../etc/passwd",
                 f"/media/{attachment.storage_name}", f"/private/{attachment.storage_name}"):
        assert client.get(path).status_code in (403, 404)


# --- who may act on a complaint, enforced on the server --------------------------------------------------


def state(complaint):
    complaint.refresh_from_db()
    return (complaint.status, complaint.department_id, complaint.assignee_id, complaint.rating,
            complaint.reopen_count, ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).count())


ACTIONS = {
    # action -> (path suffix, people who must be refused)
    "progress": ("progress", ["owner", "other_complainant", "other_staff", "other_head", "admin"]),
    "resolve": ("resolve", ["owner", "other_complainant", "head", "other_staff", "other_head", "admin"]),
    "confirm": ("confirm", ["other_complainant", "staff", "head", "other_staff", "other_head", "admin"]),
    "reject": ("reject-resolution", ["other_complainant", "staff", "head", "other_staff", "other_head", "admin"]),
}


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_unauthorised_roles_cannot_change_the_complaint(world, action):
    suffix, refused = ACTIONS[action]
    complaint = world["complaint"]
    for who in refused:
        before = state(complaint)
        response = client_for(world[who]).post(
            f"/complaints/{complaint.complaint_id}/{suffix}/",
            {"remarks": "x" * 30, "reason": "y" * 30, "rating": "5", "status": "CLOSED", "revision": "forged"},
        )
        assert response.status_code in (302, 400, 403, 404, 409), (action, who, response.status_code)
        assert state(complaint) == before, f"{who} changed the complaint through {action}"


def test_assignment_is_head_of_the_same_department_only(world, user_factory):
    complaint = world["complaint"]
    newcomer = user_factory(role="STAFF", department=world["department"])
    for who in ("owner", "other_complainant", "staff", "other_staff", "other_head", "admin"):
        before = state(complaint)
        response = client_for(world[who]).post(
            f"/complaints/{complaint.complaint_id}/assign/", {"assignee": newcomer.pk, "reason": "synthetic"})
        assert response.status_code in (302, 403, 404), (who, response.status_code)
        assert state(complaint) == before, f"{who} reassigned the complaint"
        assert Complaint.objects.get(pk=complaint.pk).assignee_id == world["staff"].pk


def test_assignment_cannot_move_a_complaint_to_staff_of_another_department(world):
    complaint = world["complaint"]
    before = state(complaint)
    client_for(world["head"]).post(
        f"/complaints/{complaint.complaint_id}/assign/", {"assignee": world["other_staff"].pk, "reason": "x"})
    assert state(complaint) == before


def test_posted_status_department_and_owner_fields_are_ignored(world):
    complaint = world["complaint"]
    before = state(complaint)
    owner_before = complaint.submitted_by_id
    client_for(world["owner"]).post(
        f"/complaints/{complaint.complaint_id}/confirm/",
        {"status": "CLOSED", "department": world["other_department"].pk, "submitted_by": world["other_complainant"].pk,
         "assignee": world["other_staff"].pk, "rating": "5"},
    )
    complaint.refresh_from_db()
    assert complaint.submitted_by_id == owner_before
    assert complaint.department_id == world["department"].pk
    assert state(complaint) == before  # still IN_PROGRESS: the owner cannot confirm unresolved work


# --- department and notification scope --------------------------------------------------------------------


def test_department_report_is_for_that_departments_head_only(world):
    path = f"/complaints/departments/{world['department'].pk}/report/"
    assert client_for(world["head"]).get(path).status_code == 200
    for who in ("other_head", "staff", "other_staff", "owner", "other_complainant"):
        assert client_for(world[who]).get(path).status_code in (403, 404), who
    assert client_for(None).get(path).status_code == 302


def test_the_queue_shows_only_the_signed_in_users_department(world, complaint_factory, user_factory):
    mine = world["complaint"]
    elsewhere = complaint_factory(department=world["other_department"], assignee=world["other_staff"],
                                  title="Elsewhere synthetic title", status=Complaint.Status.ASSIGNED)
    page = client_for(world["head"]).get("/routing/queue/").content.decode()
    assert mine.complaint_id in page and elsewhere.complaint_id not in page
    other_page = client_for(world["other_head"]).get("/routing/queue/").content.decode()
    assert elsewhere.complaint_id in other_page and mine.complaint_id not in other_page


# --- output escaping (REQ-SEC-05) ---------------------------------------------------------------------------

PAGES_FOR = {
    "owner": ["/complaints/{id}/", "/complaints/"],
    "staff": ["/complaints/{id}/work/", "/routing/queue/"],
    "head": ["/complaints/{id}/work/", "/routing/queue/",
             "/complaints/departments/{dept}/report/"],
}


@pytest.mark.parametrize("who", ["owner", "staff", "head"])
def test_user_supplied_text_is_escaped_on_every_page_that_shows_it(world, who):
    complaint = world["complaint"]
    client = client_for(world[who])
    for template in PAGES_FOR[who]:
        path = template.format(id=complaint.complaint_id, dept=world["department"].pk)
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.content.decode()
        for payload in RAW_PAYLOADS:
            assert payload not in body, f"unescaped {payload!r} on {path} for {who}"


def test_the_complaint_page_shows_the_title_escaped_not_dropped(world):
    body = client_for(world["owner"]).get(f"/complaints/{world['complaint'].complaint_id}/").content.decode()
    assert "&lt;script&gt;alert(&#x27;t&#x27;)&lt;/script&gt;" in body


def test_the_report_and_audit_screens_escape_names(world, category_factory, location_factory, department_factory):
    from accounts import reference_services as svc

    category_factory(name="<script>alert('c')</script>")
    svc.create_department(world["admin"], "<img src=x onerror=alert(9)>")
    client = client_for(world["admin"])
    for path in ("/accounts/admin-config/audit/", "/accounts/admin-config/departments/",
                 "/accounts/admin-config/reports/?date_from=2000-01-01&date_to=2100-01-01"):
        body = client.get(path).content.decode()
        assert "<img src=x onerror=alert(9)>" not in body and "<script>alert('c')</script>" not in body, path


# --- anonymous complaints stay anonymous on every page (REQ-ANON-02) -----------------------------------------


@pytest.fixture
def anonymous_case(world, complaint_factory):
    complaint = complaint_factory(
        anonymous=True, department=world["department"], assignee=world["staff"],
        status=Complaint.Status.IN_PROGRESS, title="Anonymous synthetic title",
    )
    return complaint


@pytest.mark.parametrize("who", ["staff", "head"])
def test_staff_and_head_see_anonymous_complaints_without_any_identity_or_reference(world, anonymous_case, who):
    complaint = anonymous_case
    client = client_for(world[who])
    digest = complaint.reference_digest
    emails = [user.email for user in (world["owner"], world["other_complainant"], world["admin"])]
    for template in PAGES_FOR[who]:
        path = template.format(id=complaint.complaint_id, dept=world["department"].pk)
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.content.decode()
        assert digest not in body, f"reference digest on {path}"
        assert not any(email in body for email in emails), f"account email on {path}"
    # The queue labels the reporter; the work page shows no reporter at all.
    assert "Complainant: Anonymous" in client.get("/routing/queue/").content.decode()


def test_no_other_complainant_can_read_an_anonymous_complaint(world, anonymous_case):
    path = f"/complaints/{anonymous_case.complaint_id}/"
    for who in ("owner", "other_complainant", "other_staff", "other_head", "admin"):
        assert client_for(world[who]).get(path).status_code in (403, 404), who


def test_history_of_an_anonymous_complaint_cannot_hold_an_account_or_remarks(world, anonymous_case):
    """Even if a caller passes an actor, an assignee and free text, the stored entry drops all three."""
    complaint = anonymous_case
    assert complaint.submitted_by_id is None and complaint.reference_digest
    entry = ComplaintHistory.objects.create(
        complaint_ref=complaint.complaint_id, event_type="STATUS_CHANGED", actor_kind="ANONYMOUS",
        actor=world["owner"], assignee=world["staff"], remarks="I am the person who wrote this",
    )
    entry.refresh_from_db()
    assert entry.actor_id is None and entry.assignee_id is None and entry.remarks == ""
