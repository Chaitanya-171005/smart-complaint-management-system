# B10/Q05 — Interrupted intake and private evidence recovery

Owner: Atul Suresh (F2). Reviewer: Chaitanya (`Chaitanya-171005`).
Related to #15, #14 and #21. This is the evidence/process-crash recovery slice;
scheduled escalation/auto-close, real email delivery and deployed PostgreSQL /
container replacement acceptance remain coordinated with their F3/F4 owners.

## Storage and transaction contract

Every production evidence writer must use `staged_evidence(complete_batch)` and
place its entire outermost database transaction INSIDE that context. The context
holds a shared advisory lease on the private storage DIRECTORY until commit and
exception cleanup finish. B10's authenticated adapter follows this contract.
The anonymous adapter in #71 already uses the same staging boundary; its
compatibility must be checked when integrating the branches. F4 resolution
writers must use this boundary too, with their own authorization and batch limit.
Do not call `PrivateEvidenceStorage.save()` directly and then commit metadata
outside a lease. Do not deploy mixed old/new writer versions during recovery.

Before yielding stored descriptors, storage flushes and fsyncs each file and
syncs its directory entry. These are prerequisites to acknowledging a database
commit. A failed write/sync is an intake failure, not successful acceptance.
Generated immutable file names and existing Attachment metadata are retained;
no migration or identifier/reference changes are introduced.

Cleanup after an exception consults primary Attachment metadata first. Accepted
files survive even if an exception occurs AFTER the business commit. Unreferenced
files from ordinary rollback are removed. If database state cannot be read or
a deletion fails, the original exception is preserved and cleanup is deferred
to recovery. Logs contain static operational messages, without exception text,
private paths, original filenames, account identifiers or reference values.

A killed process cannot execute finally/rollback cleanup. Its OS-held lease is
released automatically, and the database rolls back an uncommitted transaction.
A later recovery run reconciles the remaining generated files. No separate
journal stores submission bodies, accounts, sources or tracking credentials.

## Operator commands

Use the SAME primary database and private evidence volume as the application,
with its normal environment configuration. Confirm paired DB/storage backups
and use a reviewed maintenance window; do not point recovery at unrelated or
stale metadata. Do not copy genuine evidence into a public test repository.

```sh
# Preview only: integrity checks and aggregate counts; no file moves/deletes.
python manage.py reconcile_evidence

# Restore accepted quarantined bytes and quarantine unreferenced generated files.
python manage.py reconcile_evidence --apply

# Separately reviewed deletion: purge previously quarantined, still-unreferenced
# files. Newly discovered orphans always get a reversible first quarantine pass.
python manage.py reconcile_evidence --apply --purge-quarantine
```

There is no automatic purge schedule or invented retention period. F2/F4 and the
deployment owner must agree the evidence retention/backup policy before enabling
scheduled permanent deletion. Quarantine is private storage, not a download URL.

The dry-run/apply reports contain counts only: referenced files, root orphans,
files already quarantined, restorable accepted files, purge candidates and
ignored entries. `--apply` moves root orphans into `.recovery-quarantine/` with
private directory permissions. File permissions remain private. A later run
restores a quarantined file if primary Attachment metadata references its key,
size and digest and the accepted root file is missing. Accepted rows, complaints,
receipts, IDs and history are never changed or deleted by recovery.

## Refusal and retry behavior

Recovery requires an exclusive, nonblocking lease and an outermost primary-DB
view. Active staging or another recovery run produces a nonzero refusal; retry
later instead of racing the writer. All workers must share the same actual
storage directory/inode on a filesystem providing correct POSIX flock, rename
and fsync semantics. This implementation targets local Linux/macOS filesystems;
Windows, object storage and distributed/NFS semantics are not attested.

Before moving/deleting anything, recovery loads all Attachment metadata from
`default` and checks every accepted file's size and SHA-256. Missing/corrupt
accepted evidence, unsafe generated entries, conflicting copies, unavailable
metadata or symlinked root/quarantine paths fail closed. Unknown non-generated
names are left untouched. Recovery does not follow generated symlinks or
silently delete accepted metadata to make a report pass.

An interrupted move may leave some files quarantined and others in the root.
Both locations are scanned on the next run, so the operation is retryable.
An I/O error produces a nonzero outcome with sanitized text. Resolve the storage
problem and rerun the preview; do not reset the database or delete complaints.
Power-loss durability, remote filesystems, backup restoration and hardware loss
need separate deployment verification; process-death tests do not establish them.

## Verification

Run:

```sh
python -m pytest complaints/test_evidence_recovery.py --no-cov -q
python -m pytest complaints/test_evidence.py complaints/test_submission.py complaints/test_intake.py --no-cov -q
python manage.py check
python manage.py makemigrations --check --dry-run
```

Earlier Main-based verification passed 885 tests with no skips, including 30
recovery tests; every module coverage gate and Django system/migration check
passed. A separate integration checkout combining these changes with PR #73
head `1e8841e86b69cc9981eec33214ad59f69a2b3d5f` passed all 1,064 tests with no
skips and all module gates. This verifies the shared staging API and anonymous
privacy-safe cleanup behavior; the actual branch integration still needs its
normal review/merge process.

The recovery suite uses real private files, real primary Attachment rows, actual
cross-process directory locks and subprocess SIGKILL before intake, during the
required transaction and immediately after commit. It restarts/retries the same
operation key and asserts a single accepted graph. It also checks dry-run,
quarantine/restore/purge, accepted INTAKE/RESOLUTION files, corruption refusal,
symlinks, missing metadata, cleanup failures, fsync refusal, interrupted moves,
nonzero command failure and absence of private exception data from logs.

Generate full clean-source evidence only AFTER committing source:

```sh
python scripts/run_tests.py --evidence-dir docs/evidence/b10-q05-recovery
```

Keep source and evidence in separate commits. Preserve prior evidence directories.
Record the measured count and both zero exit codes. SQLite/local-filesystem
results do not close all of Q05: deployed PostgreSQL, Docker volume replacement,
F3 scheduler overlap/interruption, F4 auto-close/feedback and real mail/outbox
failure/retry acceptance remain tracked in #21 and the owning module issues.


The `Evidence crash recovery` GitHub Actions workflow runs the E02 entry point,
including the full suite and real process-death tests, on supported Linux
runners and retains sanitized evidence. Hosted run links must be recorded after
execution; a workflow file alone is not run evidence. This supplements the E03
Jenkins handoff and does not replace deployment/restart acceptance.


## PostgreSQL process-death verification

The recovery subprocesses now inherit the active pytest database configuration,
including PostgreSQL's generated test database name, host and port. A SQLite
path alone is insufficient on PostgreSQL. Test credentials are passed only in
the private child environment, never printed or written to the recovery report.
The SIGKILL cases compare the complete complaint/attachment/receipt/routing/
history/ID-sequence graph and retry the same operation after reconciliation.

`scms.recovery_postgresql_settings` is an explicit test-only settings module.
It requires every `RECOVERY_POSTGRES_*` variable and never falls back to SQLite.
It leaves production database configuration with E03. Use an isolated empty
PostgreSQL instance whose test user may create/drop its own test database; never
use a production database or production credentials. The test runner creates and
drops Django's separate test database in that instance.

```sh
python -m pip install 'psycopg[binary]==3.3.8'
# Set DJANGO_SECRET_KEY and RECOVERY_POSTGRES_NAME, USER, PASSWORD, HOST, PORT
# to the isolated test instance, then:
DJANGO_SETTINGS_MODULE=scms.recovery_postgresql_settings python manage.py check
DJANGO_SETTINGS_MODULE=scms.recovery_postgresql_settings python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=scms.recovery_postgresql_settings python integration_checks/run_recovery_postgresql.py
```

The runner checks the actual backend, records its PostgreSQL/Python/Django
versions and source revision, and requires exactly 30 executed recovery cases,
zero skips and zero failures. Its artifacts contain run.json, pytest.txt and
junit.xml. It reports component acceptance only. The `postgresql-recovery` job
in the existing Evidence crash recovery workflow starts PostgreSQL 17.6 and runs
these checks independently of the full SQLite regression/coverage job. A hosted
run link is evidence only after both jobs have actually completed successfully.

The earlier local Docker persistence run is separately recorded in PR #80 for
E03 source 526a0d31ea4a50f666b641839177a87e79c81f6b. It does not include PR #76
and must not be used as proof of this crash-reconciliation implementation.
Final merged deployment, scheduler overlap/interruption, competing auto-close
and feedback, real notification/outbox failures, and power-loss/backup recovery
remain outside this component run. Issue #21 remains open.

Preparation checks for this PostgreSQL follow-up passed all 925 Main-integrated
SQLite tests with no skips and all module gates. The 30 recovery cases also
passed on an isolated actual PostgreSQL 17.6 server, including all three
SIGKILL boundaries and cross-process writer exclusion. These preparation
results are separate from the fresh clean-source and hosted evidence recorded
when publishing the follow-up; neither closes final deployment acceptance.
