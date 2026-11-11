# Q07 final testing evidence checklist

Source: [issue #42](https://github.com/Chaitanya-171005/smart-complaint-management-system/issues/42) (NFR-QUAL-03/04, BR-06, VM-04). This is an evidence plan, not a final test report. **Final integrated delivery evidence: NOT VERIFIED.**

## Evidence rule

Identify one reviewed delivery SHA and a clean checkout. Run the shared entry point, `sh scripts/ci_checks.sh`, with a test-only `DJANGO_SECRET_KEY` and a new evidence directory. Per [CI_TEST_HANDOFF.md](CI_TEST_HANDOFF.md), retain the command, environment, job URL, console, `pytest.txt`, `coverage-summary.txt`, and `run.json`. Confirm `source_revision` equals the delivery SHA, `working_tree_dirty=false`, and both exit codes are zero. Keep failures, skips, retests, and unexecuted cases visible. A historical or component run cannot verify a later integrated revision.

## Final gates — all NOT VERIFIED

- [ ] **Traceability and scope:** link every required baseline ID to current implementation, expanded test cases, and actual evidence; record scope deviations and D09 test/security-documentation decisions. Obtain F1–F4 owner confirmation.
- [ ] **Coverage:** on the delivery SHA, record actual F1–F4 results from the coverage gate. Each module needs **line coverage ≥70% and branch coverage ≥60%**; missing/placeholder modules or missing branch data fail. See [TESTING.md](TESTING.md#coverage-gate) and `.coveragerc`. No current integrated percentages are asserted here.
- [ ] **Integrated regression:** execute the full required suite on the delivery SHA, with failures, skips, coverage exit status, and critical/high defect retests recorded. Include B15/B18 allocation and escalation with F2/F3/F4 lifecycle, resolution, feedback, notifications, and email delivery.
- [ ] **Anonymous escalation:** integrate the F2 anonymous submission/privacy source with F3 escalation and F4 notice/outbox delivery. Run the real `integration_checks/anonymous_escalation.py` from the integrated F4 source; verify `submitted_by=None`, Head notice/email, no anonymous-reporter email, no reference or identity leak, and current authorization. This check is not present in this Main checkout.
- [ ] **Authorization and privacy:** exercise complainant, Staff, Head, Admin, anonymous, revoked-role, cross-department, and reference-only boundaries across history, inbox, evidence, dashboards, and CSV. Record denied access and sanitized outputs without exposing private values in evidence.
- [ ] **Performance and recovery:** run the agreed NFR workload and recovery scenarios on the delivery environment, including storage/database interruption and scheduled escalation/auto-close competition. Record workload, limits, runtime, failures, and retests; local component results below are not deployment acceptance.
- [ ] **Q06 browser checks:** verify 320px pages have no horizontal overflow and exercise clipboard success, denial/unavailable fallback, keyboard access, and live feedback in a browser. The focused Q06 code tests in [PR #83](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/83) do not establish these browser results.
- [ ] **Pipeline gates:** link a genuine GitHub Actions job for the final SHA and a Jenkins build/deployment gate, including a controlled failed required check that prevents deployment. Actions and Jenkins have separate responsibilities under [CI_TEST_HANDOFF.md](CI_TEST_HANDOFF.md); workflow files alone are not execution evidence.
- [ ] **Final signoff:** reconcile issues, critical/high defects, unresolved decisions, owner approvals, sprint demo links, and delivery/freeze SHA. Attach the final report and genuine evidence links to #42; do not infer approval from draft PRs or historical reports.

## Existing evidence — historical only

| Record | What it can establish | Final integrated status |
| --- | --- | --- |
| [E02 CI handoff](evidence/e02-ci-handoff/run.json) | Earlier wrapper/test evidence and source metadata | NOT VERIFIED |
| [B15 allocation](evidence/b15-queue-allocation/run.json), [B18 escalation](evidence/b18-scheduled-escalation/run.json) | Earlier clean component runs at their recorded source revisions | NOT VERIFIED |
| [Q04 harness](evidence/q04-harness/run.json), [B10 recovery](evidence/b10-q05-recovery/run.json) | Earlier performance-harness and recovery evidence | NOT VERIFIED |
| [Q05 PostgreSQL component report](evidence/q05-autoclose-postgresql/README.md) | Earlier local auto-close/feedback competition; its own README lists deployment and integration limits | NOT VERIFIED |

No final metrics, screenshots, pipeline gate result, demo, or signoff is claimed by this document.
