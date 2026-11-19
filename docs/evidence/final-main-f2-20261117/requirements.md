# F2 requirement and evidence matrix

Implementation/test paths below refer to final Main `a479551c61beb2e2f6e04b93b167084bb7397dcc`. Its hosted SQLite and PostgreSQL runs each passed all 2,001 cases. Fresh focused PostgreSQL (621), process recovery (28), and Chromium (14) runs also passed. The collected case inventory is retained. Scenario descriptions below state test scope and remaining manual/deployment observations, rather than claiming every scenario was manually executed on the running image.

| Requirement/task | Implementation | Final Main tests/evidence | Scenario scope / remaining observation |
| --- | --- | --- | --- |
| B07, REQ-CMP-01, DOM-02, TC-03 | complaints/forms.py, validators.py, views.py | complaints/test_forms.py, test_http_intake.py; native Chromium invalid-description cases | Active references, required fields, Unicode limits, adjacent errors, preserved input, corrected CSRF-protected submission |
| B08, REQ-CMP-02 | complaints/identifiers.py | complaints/test_identifiers.py, test_submission.py | Real unique accepted ID, transactional rollback, retry retains original ID |
| B09, REQ-CMP-03, REQ-SEC-05, TC-05 | complaints/evidence.py, views.py | complaints/test_evidence.py; test_download_get_head_and_permission_changes_use_real_parent | Valid JPEG/PNG/PDF upload and download, malformed/oversized/batch rejection, revoked/cross-department access denied, agreed D02 boundaries |
| B10, REQ-CMP-04, TC-03, VM-01 | complaints/intake.py, submission.py | complaints/test_intake.py, test_submission.py, test_evidence_recovery.py | Required graph commits before acknowledgement, duplicate/changed retry handling, failures roll back DB/files |
| B10/Q05 recovery | complaints/evidence_recovery.py, management/commands/reconcile_evidence.py | 40 authenticated/anonymous recovery cases within regression; explicit integration_checks/anonymous_recovery.py | Process death before/during/after commit, safe retry, live writer lease, dry run nonmutation, preserve accepted files |
| B11 anonymous intake | complaints/anonymous.py, anonymous_views.py, references.py | complaints/test_anonymous.py; end-to-end anonymous escalation/assignment test | No account/source linkage, one-response-only reference, hash-only persistence, retry cannot recover raw reference |
| B12, REQ-ANON-02, REQ-SEC-06/08, BR-03 | complaints/privacy.py, privacy_middleware.py, checks.py | routing/test_b12_privacy.py, complaints/test_anonymous.py, real nginx/TLS job | Authorized safe staff outputs, no private reference/digest/text leakage, middleware ordering, deploy ingress/logging attestations remain separate |
| B13, REQ-ANON-03, REQ-SEC-06, TC-04 | complaints/tracking.py, tracking_views.py, tracking_limits.py, tracking_source.py | complaints/test_tracking.py; 9 actual Redis/TLS checks | Restricted valid tracking, uniform no-match, CSRF, shared real limiter, no credential in URL/HTML/logs, pagination <=25 |
| F2/F4 private feedback | complaints/feedback_views.py, workflow/reference_feedback.py, feedback_detail_views.py | workflow/test_reference_feedback.py, integration_checks/reference_feedback_browser.py | Confirm/rate/reopen/maximum review; all reference/digest case variants refused atomically; staff reader checks current department |
| F2/F3 intake/routing/assignment | routing/intake.py, resolver.py, sla.py, allocation.py, queue.py | routing/test_intake_*.py, test_allocation.py, test_b15_http.py, test_notification_handoff.py | Effective priority/SLA/department, Head-only assignment to eligible Staff, stale actions/rollback, escalation/outbox idempotence |
| Q04, NFR-PERF-01/02/03, TC-15 | scripts/q04_load.py, q04_env.py, q04_escalation.py | Runner correctness passes; no official load measurements yet | Execute every agreed measurement during confirmed conditions; record real timings/errors/resources/dataset and durable mutation checks |
| Q06, NFR-QUAL-02, VM-03 | Final application registration/intake/tracking UI | 14 branch Chromium checks; earlier assisted six-screen report | Genuine unaided first-time session, <=4 primary screens, desktop/320px, explicit assistance/error/fix/retest record |

Historical combined-branch evidence (separate from fresh Main logs in this folder):
https://github.com/Chaitanya-171005/smart-complaint-management-system/tree/003e4ddd2a058385826f10704b7893d72890b304/docs/evidence/pr93-main-integration-20261117

## Final execution recipe

Use a fresh isolated checkout of the resulting Main SHA. Preserve the original
developer checkout. Confirm PR93/PR100 runtime changes survived the actual merge
method; an ancestry test alone is insufficient after a squash.

Record source SHA, clean/dirty state, image digest, Python/Django/PostgreSQL,
resources and deployment settings without credentials. Activate the project
virtualenv in PATH. Use only disposable databases/evidence storage.

Run `sh scripts/ci_checks.sh` with `SCMS_CI_DATABASE_ISOLATED=1` and
`SCMS_CI_REQUIRE_F4=1` on SQLite and PostgreSQL. Do not omit the required explicit
F3/F4 checks or lower coverage gates. Follow the saved PR100 reproduction recipe
for 621 focused PostgreSQL cases, 28 process/SMTP/recovery cases, 14 Chromium cases,
and the real Redis/nginx/TLS workflow. Retain every failed attempt and subsequent
fixed-source retest. Perform actual final-image HTTP upload/intake/privacy smoke
checks under approved test-only conditions without changing persistent release
gates merely to force acceptance.

The canonical suite currently has 2,001 cases on the branch; a changed final Main
may legitimately have another count. Record actual collected/executed/failed/
errored/skipped numbers and the actual line/branch coverage instead of copying
the earlier totals.
