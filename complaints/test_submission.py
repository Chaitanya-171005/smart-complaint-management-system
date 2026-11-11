"""Real aggregate acceptance/rollback tests, using synthetic campus configuration."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from PIL import Image

from accounts.models import Location, User
from complaints import intake, submission
from complaints.evidence import evidence_download_response
from complaints.models import Attachment, Complaint, ComplaintIdSequence, IntakeReceipt
from routing.models import Category, RoutingDecision, SLAConfiguration
from routing.resolver import RoutingConfigurationError
from routing.sla import SLAConfigurationError
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db(transaction=True)


def image_upload(name="evidence.png", color="red"):
    stream = BytesIO()
    Image.new("RGB", (2, 2), color=color).save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="text/plain")


@pytest.fixture
def args(complainant_user, routing_configuration, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    config = routing_configuration
    return {"user": complainant_user, "key": intake.new_intake_key(), "data": {
        "category": str(config["category"].pk), "location": config["location"].code,
        "title": "Synthetic complaint", "description": "Synthetic description with more than twenty characters.",
        "priority": "LOW", "sub_category": "",
    }}


def stored_files(settings):
    return list(settings.PRIVATE_EVIDENCE_ROOT.glob("*"))


def assert_empty(settings):
    for model in (Complaint, Attachment, IntakeReceipt, RoutingDecision, ComplaintHistory, ComplaintIdSequence):
        assert not model.objects.exists(), model.__name__
    assert not stored_files(settings)


def test_success_persists_real_graph_before_return(args, routing_configuration, settings):
    upload = image_upload()
    expected_hash = hashlib.sha256(upload.read()).hexdigest()
    upload.seek(0)
    result = submission.submit_authenticated_complaint(**args, files=[upload])
    assert not connection.in_atomic_block and not result.replayed
    complaint = Complaint.objects.get()
    decision = RoutingDecision.objects.get()
    receipt = IntakeReceipt.objects.get()
    attachment = Attachment.objects.get()
    assert receipt.accepted_complaint == complaint
    assert complaint.complaint_id == result.complaint_id == decision.complaint_id
    assert complaint.submitted_at == result.submitted_at
    assert complaint.submitted_by == args["user"] and complaint.reference_digest is None
    assert complaint.category_key == args["data"]["category"]
    assert complaint.category == routing_configuration["category"].name
    assert complaint.location_code == args["data"]["location"]
    assert complaint.department == decision.department == routing_configuration["department"]
    assert complaint.status == "ASSIGNED" and complaint.unrouted is False
    assert complaint.routing_rule_key == str(routing_configuration["rule"].pk)
    assert complaint.due_at == result.submitted_at + timedelta(minutes=120)
    assert attachment.complaint == complaint and attachment.uploaded_by == args["user"]
    assert attachment.stage == "INTAKE" and attachment.content_type == "image/png"
    assert attachment.sha256 == expected_hash
    assert hashlib.sha256(stored_files(settings)[0].read_bytes()).hexdigest() == expected_hash
    assert list(ComplaintHistory.objects.values_list("event_type", "previous_state", "new_state")) == [
        ("SUBMITTED", "", "SUBMITTED"), ("ALLOCATED", "SUBMITTED", "ASSIGNED"),
    ]


def test_category_minimum_and_sla_are_persisted(args, routing_configuration, sla_factory):
    category = routing_configuration["category"]
    Category.objects.filter(pk=category.pk).update(minimum_priority="HIGH")
    sla_factory(category=category, priority="HIGH", duration_minutes=17)
    result = submission.submit_authenticated_complaint(**args)
    complaint = Complaint.objects.get()
    assert complaint.priority == "HIGH"
    assert complaint.due_at == result.submitted_at + timedelta(minutes=17)


def test_fallback_is_assigned_with_empty_rule_key(args, routing_configuration):
    rule = routing_configuration["rule"]
    rule.active = False
    rule.save()
    submission.submit_authenticated_complaint(**args)
    complaint = Complaint.objects.get()
    assert complaint.status == "ASSIGNED" and complaint.unrouted is True
    assert complaint.routing_rule_key == "" and RoutingDecision.objects.get().rule_id is None


def test_timeout_replay_survives_policy_changes_and_cleans_new_files(args, settings):
    first = submission.submit_authenticated_complaint(**args, files=[image_upload()])
    original = Complaint.objects.get()
    original_due_at = original.due_at
    original_priority = original.priority
    original_file = stored_files(settings)[0]
    Category.objects.filter(pk=args["data"]["category"]).update(active=False, name="Renamed category")
    Location.objects.filter(code=args["data"]["location"]).update(active=False)
    SLAConfiguration.objects.update(active=False)
    connection.close()
    replay = submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert replay.replayed and replay.complaint_id == first.complaint_id
    original.refresh_from_db()
    assert original.due_at == original_due_at and original.priority == original_priority
    assert stored_files(settings) == [original_file]
    assert Complaint.objects.count() == IntakeReceipt.objects.count() == RoutingDecision.objects.count() == 1
    assert Attachment.objects.count() == 1 and ComplaintHistory.objects.count() == 2
    assert ComplaintIdSequence.objects.get().last_value == 1


@pytest.mark.parametrize("change", ["title", "priority", "file_bytes", "file_name", "file_order"])
def test_changed_retry_is_refused_without_touching_original(args, settings, change):
    original_files = [image_upload(), image_upload("second.png", "blue")]
    submission.submit_authenticated_complaint(**args, files=original_files)
    paths = set(stored_files(settings))
    data = dict(args["data"])
    files = [image_upload(), image_upload("second.png", "blue")]
    if change == "title":
        data["title"] = "Changed title"
    elif change == "priority":
        data["priority"] = "MEDIUM"
    elif change == "file_bytes":
        files[0] = image_upload(color="green")
    elif change == "file_name":
        files[0] = image_upload("renamed.png")
    else:
        files.reverse()
    with pytest.raises(intake.IdempotencyConflict):
        submission.submit_authenticated_complaint(**{**args, "data": data}, files=files)
    assert set(stored_files(settings)) == paths
    assert Complaint.objects.count() == 1 and ComplaintHistory.objects.count() == 2


def test_unicode_is_normalized_before_validation_storage_and_retry(args):
    data = {**args["data"], "title": "Cafe\u0301 issue"}
    first = submission.submit_authenticated_complaint(**{**args, "data": data}, files=[image_upload("cafe\u0301.png")])
    data["title"] = "Caf\u00e9 issue"
    replay = submission.submit_authenticated_complaint(**{**args, "data": data}, files=[image_upload("caf\u00e9.png")])
    assert replay.replayed and replay.complaint_id == first.complaint_id
    assert Complaint.objects.get().title == "Caf\u00e9 issue"
    assert Attachment.objects.get().original_name == "caf\u00e9.png"


@pytest.mark.parametrize("target", [
    "routing.intake.route_and_record", "routing.intake.derive_priority_and_due",
    "complaints.submission.record_history", "complaints.submission.Attachment.objects.create",
    "complaints.intake.IntakeReceipt.objects.create", "database_commit",
])
def test_required_failures_rollback_graph_identifier_and_files(args, settings, target):
    error = IntegrityError if target == "database_commit" else RuntimeError
    # Patch the active connection, including an instance-bound method restored
    # by an earlier guard test; a class patch can be shadowed by that method.
    failure = (patch.object(connection, "commit", side_effect=error("controlled required failure"))
               if target == "database_commit"
               else patch(target, side_effect=error("controlled required failure")))
    with failure:
        with pytest.raises(error):
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)
    result = submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert result.complaint_id.endswith("000001")


@pytest.mark.parametrize("failure,error", [("routing", RoutingConfigurationError), ("sla", SLAConfigurationError)])
def test_real_configuration_errors_propagate_without_acceptance(args, routing_configuration, settings, failure, error):
    if failure == "routing":
        rule = routing_configuration["rule"]
        rule.active = False
        rule.save()
        department = routing_configuration["policy"].default_department
        department.active = False
        department.save()
    else:
        SLAConfiguration.objects.update(active=False)
    with pytest.raises(error):
        submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


def test_second_history_failure_removes_first_event_too(args, settings):
    real_record = submission.record_history
    def fail_allocation(*params, **kwargs):
        if params[1] == "ALLOCATED":
            raise RuntimeError("controlled second history failure")
        return real_record(*params, **kwargs)
    with patch("complaints.submission.record_history", side_effect=fail_allocation):
        with pytest.raises(RuntimeError):
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


def test_partial_storage_failure_removes_first_file(args, settings):
    from complaints.evidence import PrivateEvidenceStorage
    real_save = PrivateEvidenceStorage.save
    calls = []
    def fail_second(storage, *params, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("controlled storage failure")
        return real_save(storage, *params, **kwargs)
    with patch.object(PrivateEvidenceStorage, "save", fail_second):
        with pytest.raises(OSError):
            submission.submit_authenticated_complaint(**args, files=[image_upload(), image_upload("two.png")])
    assert_empty(settings)


@pytest.mark.parametrize("field,value", [
    ("description", "short"), ("category", "999999999999999999999999999999999"),
    ("category", "0"), ("location", "bad/code"), ("priority", "ADMIN"),
    ("title", 42), ("department", "1"),
])
def test_invalid_or_derived_fields_refused_before_storage(args, settings, field, value):
    with pytest.raises(ValidationError):
        submission.submit_authenticated_complaint(**{**args, "data": {**args["data"], field: value}}, files=[image_upload()])
    assert_empty(settings)


@pytest.mark.parametrize("model,selector,field", [
    (Category, "category", "name"), (Location, "location", "block"),
])
def test_invalid_active_reference_text_rolls_back_staged_files(args, settings, model, selector, field):
    query = {"pk" if selector == "category" else "code": args["data"][selector]}
    model.objects.filter(**query).update(**{field: "Invalid\nreference"})
    with patch.object(submission, "route_and_prioritize") as route:
        with pytest.raises(ValidationError) as error:
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
        assert "__all__" in error.value.message_dict
        route.assert_not_called()
    assert_empty(settings)


@pytest.mark.parametrize("model,selector", [(Category, "category"), (Location, "location")])
def test_inactive_reference_is_rechecked_after_staging(args, settings, model, selector):
    from complaints.evidence import PrivateEvidenceStorage
    real_save = PrivateEvidenceStorage.save
    def deactivate(storage, *params, **kwargs):
        name = real_save(storage, *params, **kwargs)
        query = {"pk" if selector == "category" else "code": args["data"][selector]}
        model.objects.filter(**query).update(active=False)
        return name
    with patch.object(PrivateEvidenceStorage, "save", deactivate):
        with pytest.raises(ValidationError):
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


@pytest.mark.parametrize("files", [lambda: [image_upload() for _ in range(4)],
                                   lambda: [SimpleUploadedFile("bad.png", b"invalid")]])
def test_invalid_batch_never_leaves_files(args, settings, files):
    with pytest.raises(ValidationError):
        submission.submit_authenticated_complaint(**args, files=files())
    assert_empty(settings)


def test_anonymous_or_stale_inactive_user_cannot_stage(args, settings):
    with pytest.raises(PermissionDenied):
        submission.submit_authenticated_complaint(**{**args, "user": AnonymousUser()}, files=[image_upload()])
    User.objects.filter(pk=args["user"].pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


def test_permission_change_during_storage_rolls_back(args, settings):
    from complaints.evidence import PrivateEvidenceStorage
    real_save = PrivateEvidenceStorage.save
    def deactivate(storage, *params, **kwargs):
        name = real_save(storage, *params, **kwargs)
        User.objects.filter(pk=args["user"].pk).update(is_active=False)
        return name
    with patch.object(PrivateEvidenceStorage, "save", deactivate):
        with pytest.raises(PermissionDenied):
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


def test_real_attachment_download_uses_its_own_parent(args, user_factory):
    from django.http import Http404
    submission.submit_authenticated_complaint(**args, files=[image_upload()])
    attachment = Attachment.objects.select_related("complaint").get()
    response = evidence_download_response(user=args["user"], attachment=attachment)
    assert response.status_code == 200 and b"".join(response.streaming_content)
    response.close()
    with pytest.raises(Http404):
        evidence_download_response(user=user_factory(), attachment=attachment)
    with pytest.raises(Http404):
        evidence_download_response(user=AnonymousUser(), attachment=attachment)


def test_legacy_unlinked_receipt_cannot_be_reported_as_real_acceptance(args, settings):
    fingerprint = submission.submission_digest(fields={**submission._clean_fields(args["data"]), "evidence": []})
    intake.execute_intake(user=args["user"], key=args["key"], payload_digest=fingerprint,
                          operation=lambda context: None)
    with pytest.raises(intake.IntakeReconciliationRequired):
        submission.submit_authenticated_complaint(**args)
    assert not Complaint.objects.exists()
    assert IntakeReceipt.objects.get().accepted_complaint_id is None
    assert ComplaintIdSequence.objects.get().last_value == 1


def test_receipt_cannot_link_another_identifier(args, complaint_factory):
    submission.submit_authenticated_complaint(**args)
    other = complaint_factory()
    with pytest.raises(IntegrityError), transaction.atomic():
        IntakeReceipt.objects.update(accepted_complaint=other)


def test_receipt_migration_preserves_and_links_only_exact_matches(args, complaint_factory, user_factory):
    from django.db.migrations.executor import MigrationExecutor

    matching = complaint_factory(submitted_by=args["user"])
    wrong_owner = complaint_factory(submitted_by=user_factory())
    wrong_time = complaint_factory(submitted_by=args["user"])
    before = set(Complaint.objects.values_list("complaint_id", flat=True))
    old = [("complaints", "0003_complaint")]
    executor = MigrationExecutor(connection)
    # Restore the complete schema: dependent app migrations are unapplied when
    # rolling back complaints, including B26's outbox and future additions.
    new = executor.loader.graph.leaf_nodes()
    executor.migrate(old)
    try:
        apps = executor.loader.project_state(old).apps
        receipts = apps.get_model("complaints", "IntakeReceipt")
        for index, identifier, timestamp in (
            (1, matching.complaint_id, matching.submitted_at),
            (2, wrong_owner.complaint_id, wrong_owner.submitted_at),
            (3, wrong_time.complaint_id, wrong_time.submitted_at + timedelta(seconds=1)),
            (4, "SCMS-2000-999999", matching.submitted_at),
        ):
            receipts.objects.create(user_id=args["user"].pk, key_digest=str(index) * 64,
                                    payload_digest="a" * 64, complaint_id=identifier,
                                    submitted_at=timestamp)
    finally:
        MigrationExecutor(connection).migrate(new)
    assert set(Complaint.objects.values_list("complaint_id", flat=True)) == before
    assert IntakeReceipt.objects.count() == 4
    assert IntakeReceipt.objects.get(complaint_id=matching.complaint_id).accepted_complaint_id == matching.complaint_id
    assert IntakeReceipt.objects.filter(accepted_complaint__isnull=True).count() == 3


def test_same_key_on_two_accounts_is_not_a_replay(args, user_factory):
    first = submission.submit_authenticated_complaint(**args)
    second = submission.submit_authenticated_complaint(**{**args, "user": user_factory()})
    assert not second.replayed and first.complaint_id != second.complaint_id
    assert Complaint.objects.count() == IntakeReceipt.objects.count() == 2


def test_outer_transaction_refused(args, settings):
    with transaction.atomic():
        with pytest.raises(TransactionManagementError):
            submission.submit_authenticated_complaint(**args, files=[image_upload()])
    assert_empty(settings)


def test_concurrent_same_key_creates_one_real_aggregate(args, settings):
    barrier = threading.Barrier(2)
    def submit():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return submission.submit_authenticated_complaint(**args, files=[image_upload()])
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.complaint_id for result in results}) == 1
    assert Complaint.objects.count() == RoutingDecision.objects.count() == Attachment.objects.count() == 1
    assert ComplaintHistory.objects.count() == 2 and len(stored_files(settings)) == 1
