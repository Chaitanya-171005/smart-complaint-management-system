# E04 — branch, review and sprint evidence workflow

Source: [issue #40](https://github.com/Chaitanya-171005/smart-complaint-management-system/issues/40).
Status: documented workflow; E04 delivery acceptance remains incomplete.
VERIFIED below means observed evidence or an existing documented contract.
PROPOSED means a procedure needing team adoption, not an approval or completed action.

## VERIFIED practices and evidence

- Feature work is submitted through PRs: [#77](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/77)
  targets Main at `cda6fc5`; [#78](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/78)
  is stacked on feature/B21-history-integration-tanmay at `9b163a2`.
  Both remain open drafts and unmerged; review and acceptance remain pending.
- Genuine peer review exists elsewhere: [#72](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/72)
  received approval and merged. This does not approve #77/#78.
- Main includes targeted GitHub Actions workflows for evidence recovery and Q04.
  Genuine successful B13 runs were observed for
  [push](https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/42863228233)
  and [PR](https://github.com/Chaitanya-171005/smart-complaint-management-system/actions/runs/42863235781).
  These runs do not establish general F4 CI coverage.
- [CI_TEST_HANDOFF.md](CI_TEST_HANDOFF.md) documents the shared check entry point,
  evidence requirements and pipeline ownership. Historical evidence exists in
  [docs/evidence/e02-ci-handoff/run.json](evidence/e02-ci-handoff/run.json).
  Historical runs are not final-version verification.
- No Sprint 1/Sprint 2 demo-video files or links were located in the inspected
  checkout. No final freeze approval or final delivery package is evidenced here.

## PROPOSED feature branches and required peer review

1. Start a named feature branch from the reviewed dependency commit; record that
   base SHA and issue IDs. Preserve unrelated local work and HANDOVER.md. Do not
   include secrets, databases, caches or generated artifacts as implementation.
2. Open a draft PR early. State scope, dependencies, actual test commands/results,
   migrations and unresolved decisions. Use a stacked base when its parent PR is
   unmerged so reviewers see only the follow-up changes.
3. Require at least one genuine non-author peer approval before merge, plus
   affected F1/F2/F3 owner review for authorization, evidence, migration or shared
   service changes. E04 requires peer review; this specific approval threshold
   is proposed, not verified branch-protection configuration.
4. Resolve review requests and rerun affected checks on the final revision before
   requesting readiness. Do not equate code presence, focused passes or a draft
   PR with issue acceptance. Update Project status only to match real progress.
5. Merge only after explicit team authorization. After a parent merges, inspect
   ancestry and merge method before retargeting its child; a squash merge may
   require a separately reviewed reconciliation. Never silently force-push.

## PROPOSED dependency and integration order

- Main includes B15 allocation / [PR #68](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/68)
  and B18 scheduled escalation / [PR #70](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/70).
  PR #77 integrates them into F4, but remains unmerged.
- B22 integration remains pending teammate confirmation. Reconcile overlapping
  [PR #49](https://github.com/Chaitanya-171005/smart-complaint-management-system/pull/49)
  resolution work and F2 evidence contracts before accepting the final composition.
- PR #77 joins B15's workflow 0003 actor migration with B26/B27 through empty
  `0005_merge_b15_f4`; stacked PR #78 joins that chain with B28 through empty
  `0006_merge_b15_f4_b28`. Both joins passed targeted migration checks, but
  neither PR is merged into Main.
- Exercise actual assignment/escalation, stale actions, atomic history/notices,
  proof rollback/privacy and feedback/auto-close competition against integrated
  sources. Use integration_checks/lifecycle_f3.py, resolution_f3.py and
  anonymous_escalation.py only with their required teammate sources present.
- Keep anonymous feedback blocked until F2 B13 authorization is integrated and
  reviewed. D03/B30 reporting, D04 reopen SLA and D05 expiry remain outstanding;
  proposed policy must never be presented as approved.

## VERIFIED responsibilities; PROPOSED pipeline completion

Per [CI_TEST_HANDOFF.md](CI_TEST_HANDOFF.md): Tanmay owns Actions triggers/job
wiring; Chaitanya owns Jenkins build/deployment; coordinate test/coverage
integration with Atul (E02). Actions does not replace Jenkins.

Proposed completion: configure the agreed checks on relevant push/PR events,
using sh scripts/ci_checks.sh after dependency installation. It runs Django
checks, migration drift, tests and per-module coverage gates. Use an exported
test-only DJANGO_SECRET_KEY and isolated workspace/database; never production
credentials. Retain genuine successful and controlled-failure job evidence and
verify required failures prevent deployment. Archive console/job URL, source SHA,
pytest.txt, coverage-summary.txt and run.json, including failure artifacts.
Do not claim local execution proves Jenkins or Actions deployment gates.

## Required sprint evidence; PROPOSED collection procedure

Issue #40 requires Sprint 1's one-minute demo and Sprint 2's two-minute demo,
genuine commits/PRs/reviews/checks, accurate Project status and an end-of-Sprint-2
freeze. All members contribute; the coordinator collects links rather than
inventing or backfilling approvals.

For each sprint, retain owner/points/sprint/requirement/test links on issues,
actual PR/review/commit references, recorded demo URL and duration, execution
revision/environment/results, defects, retests and unresolved scope decisions.
Confirm recording access permissions and that the demonstration matches the
identified revision. Both sprint packages and videos remain unverified until
real evidence is linked.

## PROPOSED final freeze procedure

1. Team confirms the actual end-of-Sprint-2 deadline, delivery scope and owners;
   record time/timezone. No deadline or freeze approval is invented here.
2. Finish approved dependency integration and review; identify one delivery SHA.
3. Run final regression, coverage, security/NFR and integration verification on
   that version. Record failures and unexecuted cases honestly; D09 expanded
   test/security-documentation alignment still needs agreement.
4. Obtain owner sign-offs, link both sprint videos and CI/Jenkins evidence, and
   reconcile Project/issue status with accepted scope and explicit blockers.
5. Record the frozen SHA and delivery links. Tag/publish only with authorization.
   Stop feature changes after freeze. An urgent exception needs recorded approval,
   impact review, affected retests and an updated delivery SHA/evidence package.

This document creates no reviews, CI jobs, recordings, approvals or freeze record.
