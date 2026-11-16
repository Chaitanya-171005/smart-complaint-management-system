# PR #82 F3 anonymous privacy integration — 2026-11-16

Verdict: integration candidate implemented; available F3 privacy checks pass.
Full acceptance remains conditional on unrestricted socket and PostgreSQL checks
and future F4 output integration. No application defect was identified in the
reviewed F3 output paths.

## Source and isolation

- Target `refs/remotes/origin/Main`: `2595c57776f8bb4de046d4d2cc18f0e52526e46c`.
- Source `refs/remotes/origin/feature/B12-anonymous-safe-F3` and PR head
  `refs/remotes/origin/pr82` both equal `7759ca3107d9aadd0c86cb12e2441fc44d0c4f5f`.
- Used the user-confirmed fetched local refs; no remote freshness claim beyond
  that fetch. The source SHA is unchanged from the earlier blocked attempt.
- Clean merge commit: `04f10d8d7d704ed718dbff3a0585c7bb67769009`.
- Tested implementation commit: `3c2f1e5fc3002e19002bfd7ca31f29aa88df1fec`.
- Branch: `integration/pr82-f3-privacy`.
- Worktree: `/tmp/scms-pr82-f3-candidate`, backed by the separate local clone
  `/tmp/scms-pr82-f3-isolated`. Original `.git` ref writes are sandbox-denied,
  so the integration branch and worktree are registered only in this clone.
- Original checkout and contributor branches were not modified. Original
  untracked `.env.docker`, `build/` and `docs/evidence/q04-environment-readiness/`
  were preserved. No existing Docker, database or Q04 resources were used.

## Changed files and behavior

| File | Change |
| --- | --- |
| complaints/privacy.py | Adds priority to the anonymous output allowlist |
| complaints/test_anonymous.py | Updates the exact allowlist assertion |
| routing/queue.py | Preloads submitter relations for authenticated labels |
| routing/views.py | Creates privacy-aware queue display items after authorization |
| routing/templates/routing/queue.html | Generic anonymous title and allowlisted operational display |
| routing/test_b12_privacy.py | Six source tests plus nine additional regression cases |
| docs/B12_PRIVACY.md | Source PR privacy contract and historical evidence |
| docs/PR82_F3_INTEGRATION_REPORT.md | This independent integration report |

Reviewed the complete seven-file PR diff. Anonymous queue rows omit title,
description, detailed location fields, submitter relations, raw reference and
reference digest. Public complaint ID, category, location code, status, priority,
escalation state and operational assignee remain visible to authorized staff and
Heads. Authenticated rows retain their existing display. Department scoping is
unchanged. Queue context still contains internal model objects; the rendered
template is the audited output boundary, not a serializable API contract.

Assignment/reassignment work without a reporter account. Generic validation
errors omit private data; cross-department refusal audit records use the label
`anonymous complaint` without a complaint ID. Routing decisions, system escalation
history, scheduler errors and console output do not copy anonymous complaint
text or private reference data in the tested paths. Repeated assignment does not
create duplicate history; an immediate repeated escalation does not duplicate a
notice or history event. Notification-hook exceptions retain generic counters.

No CSV/export/report endpoints or production notification service exist in this
target. The escalation default hook is a no-op; a supplied callback receives the
internal Complaint object. The existing locmem integration check and additional
hook tests explicitly use `anonymous_summary`; arbitrary future callbacks are
not automatically sanitized by F3. F4 delivery/export must separately authorize
and project its output. No unimplemented endpoint is counted as accepted.

## Verification

Used the existing Python virtual environment with an explicit test-only secret,
SQLite engine, and no deployment environment files. Commands ran in the candidate.

| Check | Result |
| --- | --- |
| Initial focused routing, anonymous and explicit integration checks | 295 passed, 2 subtests passed |
| Final focused checks including added regressions | 304 passed, 2 subtests passed, 20.67s |
| Privacy module rerun after implementation commit | 15 passed, 0.68s |
| Full default regression suite | 1,201 passed, 2 failed, 13 setup errors, 40.16s |
| Coverage gate | PASS for all four modules |
| Django system check | No issues, 0 silenced |
| makemigrations --check --dry-run | No changes detected |
| migrate --noinput on fresh candidate SQLite database | All migrations applied |
| migrate --check | Exit 0 |
| git diff --check | Passed |

Focused command:

```sh
python -m pytest routing complaints/test_anonymous.py \
  integration_checks/anonymous_escalation.py \
  integration_checks/anonymous_recovery.py --no-cov -q
```

Full verification used `sh scripts/ci_checks.sh build/evidence/pr82-integration`
with `SCMS_CI_PYTHON` set to the existing virtual environment Python. The runner
correctly returned failure for the non-passing regression cases; the shell tail
used to display its log is not its acceptance result. Its `run.json` records
pytest exit 1 and coverage gate exit 0. The full run tested merge commit plus the
exact test diff subsequently committed as `3c2f1e5`; only documentation follows.

| Module | Line coverage | Branch coverage |
| --- | ---: | ---: |
| accounts | 98.51% | 96.79% |
| complaints | 98.32% | 96.59% |
| routing | 93.77% | 85.15% |
| workflow | 92.73% | 95.00% |

## Environmental restrictions and remaining risks

- All 15 non-passing regression cases fail at local socket binding with
  `PermissionError: [Errno 1] Operation not permitted`: two Docker image health
  tests and thirteen Q04 HTTP fixture tests. A separate unchanged target worktree
  reproduced **2 failed, 28 passed, 13 errors** when running
  `test_q04_load.py test_docker_files.py --no-cov -q`. These are environmental
  failures, not PR #82 regressions. No tests were skipped or weakened to hide them.
- Fresh PostgreSQL initialization with `/Library/PostgreSQL/18/bin/initdb`
  failed at `shmget` with `could not create shared memory segment: Operation not
  permitted`. PostgreSQL-specific crash/lease acceptance remains unverified.
  The temporary failed cluster was removed by initdb; no server was started.
- Django request warnings include the public complaint ID in assignment URLs.
  The tested logs omit complaint text and private reference data. Proxy/APM
  request logging needs its existing deployment privacy review.
- Staff-authored reassignment reasons are retained as history; this change does
  not claim to anonymize arbitrary human-authored text or decide campus policy.
- Production F4 notices, exports, delivery and deployment privacy acceptance
  remain outside this candidate. Release privacy flags were not enabled.
- No push, Main merge, contributor-branch mutation or PR/issue closure occurred.

Evidence: `build/evidence/pr82-integration/{pytest.txt,coverage-summary.txt,run.json}`
and `coverage.json` in the candidate. Focused logs and baseline/environment
diagnostics are copied alongside these files. Rerun socket and PostgreSQL checks
in an unrestricted isolated environment before declaring complete acceptance.
