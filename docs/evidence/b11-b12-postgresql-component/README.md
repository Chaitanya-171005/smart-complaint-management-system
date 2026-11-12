# B11/B12 — PostgreSQL anonymous intake, privacy and evidence verification

Atul ran this isolated Docker check on 12 November 2026 (India), starting
11 November 2026 at 18:44:04 UTC. All 171 selected cases passed in 30.34 seconds,
with zero skips/failures/errors. Actual runtime: PostgreSQL 17.6,
Python 3.14.10, Django 6.1.3. Django system/migration consistency checks passed.

Clean application source: PR71 `e91c9a1fe719209ed9fcc235b2a244eedcfc59b8`.
Included Main: `5c375e7da1ae43a4bfaf4972528f1ae2e79d928e`.
Git tree: `026e517d812371650e89011cba97257fd13e60bf`.
This records a targeted PostgreSQL component suite, not the full application
regression suite on PostgreSQL or final F3/F4/deployment acceptance.

| Source test file | Executed cases |
| --- | ---: |
| complaints/test_anonymous.py | 92 |
| complaints/test_evidence.py | 74 |
| integration_checks/anonymous_recovery.py | 4 |
| integration_checks/anonymous_escalation.py | 1 |
| Total | 171 |

Coverage includes anonymous HTTP/session/account isolation, CSRF/cross-origin
refusal, HTTPS configuration checks, one-time references and retries,
concurrent submissions, private storage and commit/history failure cleanup,
metadata stripping, both proposed D02 evidence boundaries, actual anonymous
process death and writer/recovery lock exclusion. The B18 contract uses a
controlled locmem Head notification hook, not production F4/email delivery.
The HTTP tests use synthetic test-only release overrides in an isolated test
environment; no real public endpoint or anonymous release flag is enabled.

`report.json` is the unchanged uploaded report. The publisher verifies the
original local JUnit SHA256, the exact 171 passing case identities and their
durations, then records a sanitized summary in `case-results.json`.
The exact expected list was independently collected and tested during
preparation. The archived runner/settings/driver/Dockerfile hashes match
the report. Source test files are in the repository at the pinned revision.
Python harness copies use `.py.txt`, so default pytest discovery does not
collect archived component tests from this evidence directory.

Validate the recorded artifacts with:

```bash
python docs/evidence/b11-b12-postgresql-component/verify_report.py
```

The original measurement package is
`B11_B12_PostgreSQL_Component_Check_20261112.zip`.
Its driver source is archived under sources/run_task.py.txt. It checks the
clean pinned source, creates a private detached worktree and Docker project,
and invokes the archived runner against PostgreSQL 17.6. No published host
ports, real campus accounts, external email credentials, private.env, raw
references, messages or raw JUnit are included in this evidence publication.

D01 campus confirmation, D02 size agreement, F3/F4 anonymous-safe consumers,
real notification privacy/delivery, deployed TLS/proxy/HSTS/secure-cookie and
external log-redaction checks, and final combined release acceptance remain
pending. Passing checks for both proposed upload limits does not decide D02.
Issues #16/#17/#21 and anonymous release acceptance are not closed by this run.
