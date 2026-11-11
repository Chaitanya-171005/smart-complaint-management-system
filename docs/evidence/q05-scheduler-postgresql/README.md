# Q05: PostgreSQL scheduler business-state recovery evidence

Related to #21 and PR #70. Atul ran the supplied Docker harness locally on November 11, 2026. It recorded PASS_BUSINESS_RECOVERY_CHECKS: six cases passed, zero skipped, zero failed/errored. The report's harness, driver and Dockerfile hashes match the exact archived source bytes here.

## Application and runtime provenance

- B18 / PR70: 2a0697bbbf88a6ca8d67a64ecb69a466897e7bd8.
- Main: ebc8ffdf9c1ae37365fad71c084869c73a35b4d0.
- Application tree after combining those sources: ae0723f2a34ffbb932b7c6dd2ea5b81e1616f4a3.
- Local source-merge commit: 3b94f58b741e0d4061e56a87f47ca0a36f78c135. This local candidate commit is not a claim that PR70 or the application merge has been published/merged. The parent commits and resulting tree make the application content reproducible independently of local commit metadata.
- Recorded start: 2026-11-11 03:27:07 UTC / 08:57:07 IST.
- Actual runtime: PostgreSQL 17.6, Python 3.14.10, Django 6.1.3.
- Original report SHA256: 668b4220ea9cff4746138b7f7fda98057b433027f7e0d2e4b6e6fe605230c2ef.

The local publisher derives case-results.json from the original run's JUnit file, accepting exactly the six named passing cases and recording the original XML hash. It copies only names, pass outcomes and numeric durations; no arbitrary XML properties or captured output are published.

## Observed cases

| Case | Business-state result |
| --- | --- |
| Two simultaneous processes | Both reach the same candidate boundary before release; one escalates and the other skips after PostgreSQL locking/recheck; one history event. |
| Repeat/interval/maximum | Same-time retries and the pre-boundary run do not advance; the recorded-history interval boundary advances once; maximum level caps further work. |
| SIGKILL before commit | History-write interruption rolls back escalation/history; later execution accepts exactly one escalation. |
| SIGKILL after commit | Committed escalation/history survive process death; later execution does not duplicate them. |
| Required history failure | Escalation rolls back, the run records failure, and retry succeeds once. |
| Controlled callback failure | Business commit survives; a same-time repeat creates no duplicate. This is not actual email/outbox delivery. |

Every case also preserves complaint ID, status, priority, department, due time and submitter.

## Open limitation and acceptance scope

Both SIGKILL cases observe that the killed worker's EscalationRun row remains RUNNING with no finish time. A subsequent business retry is safe but does not finalize that abandoned audit row. Supervision/reconciliation of abandoned runs remains pending with the deployment/F3 owner; these tests do not claim that it is repaired.

The callback failure is controlled injection into B18's notification hook. Actual F4 delivery, outbox retries and recipient correctness remain pending. No cron or Jenkins scheduler is deployed by this harness. Auto-close versus feedback and final merged deployment validation are also pending. Issue #21 remains open; this does not establish Sprint 2 completion or replace Jenkins proof.

The separate q05-docker-postgresql evidence folder records persistence for the earlier E03 snapshot. PR76 independently records PostgreSQL evidence-crash recovery CI. These source snapshots and test counts must not be combined into a claim of final application acceptance.

## Verify and reproduce

```sh
python3 docs/evidence/q05-scheduler-postgresql/verify_report.py
```

Source payloads use .py.txt filenames so pytest will not collect an archived component suite as ordinary application tests. The bytes and hashes are preserved. With Docker Desktop running, the following rebuilds the executable ZIP from these files and runs the isolated check from a repository clone:

```sh
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

base = Path('docs/evidence/q05-scheduler-postgresql/sources')
with TemporaryDirectory(prefix='q05-scheduler-') as directory:
    bundle = Path(directory)/'check.zip'
    with zipfile.ZipFile(bundle, 'w') as archive:
        for path in base.rglob('*'):
            if path.is_file():
                name = str(path.relative_to(base))
                archive.write(path, name[:-4] if name.endswith('.txt') else name)
    exec(compile((base/'run_task.py.txt').read_bytes(), 'run_task.py', 'exec'), {
        '__name__': '__main__', 'BUNDLE_PATH': bundle,
    })
PY
```

The launcher requires the recorded branch tips and expected application tree and stops if they changed. A reproduction creates a new isolated candidate worktree/Compose project, synthetic database and report; it does not overwrite this evidence. Only tracked application files and the hashed harness enter the image. Credentials remain outside the build context. Containers are stopped after execution and named volumes retained. Never commit private.env.
