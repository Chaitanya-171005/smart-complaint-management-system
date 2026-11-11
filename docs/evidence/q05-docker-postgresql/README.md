# Q05: local Docker/PostgreSQL component evidence

Related to #21; deployment foundation coordinated through #27. These are component results for the exact E03 snapshot below. They do not close Q05 or establish final merged application acceptance.

## Provenance and observed result

Atul ran the supplied checks locally with Docker Desktop. The uploaded, unmodified report records **PASS_COMPONENT_CHECKS** for all five phases. The report's driver and probe SHA256 values match the included source files.

- Repository: Chaitanya-171005/smart-complaint-management-system.
- Tested branch: feature/E03-docker-jenkins.
- Tested clean source: `526a0d31ea4a50f666b641839177a87e79c81f6b`.
- Run: `5a1824820786`.
- Recorded UTC interval: 2026-11-10 18:29:46 to 18:31:45 (23:59:46 IST on November 10 to 00:01:45 IST on November 11).
- Runtime reported inside the app: PostgreSQL 17.6, Python 3.14.10, Django 6.1.3.
- Original report SHA256: `25450d9c7b7b5f63c16a6513381b25bb8c4fdb108c02515fbff05cdc91da3080`.
- The application and database image digests are retained in report.json.

| Phase | Observed result |
| --- | --- |
| Build and seed | Real intake succeeded; two concurrent same-key requests produced one acceptance and one replay. Injected history, receipt, commit and storage errors preserved the accepted graph and evidence. |
| App restart | Graph digest and attachment hashes unchanged; retry replayed without duplication. |
| App container replacement | App container identity changed; named volumes, graph and attachment hashes persisted; retry replayed. |
| PostgreSQL restart | Graph and evidence persisted; retry replayed. |
| Full stack replacement | Both app and database containers were replaced using retained named volumes; graph and evidence persisted; retry replayed. |

Every phase retains the same business-row SHA256 and counts: 2 complaints, 2 attachments, 2 intake receipts, 2 routing decisions, 4 history records and 1 ID-sequence row. Both evidence files were checked for exact size and SHA256. The driver asserts named-volume identity and actual container replacement before recording each phase as PASS. Container identifiers and volume names are not separately exported as a phase transcript; the source records the assertions used.

## Isolation and limits

The driver creates a unique Compose project, separate PostgreSQL/evidence named volumes and explicitly synthetic reference data. It uses an unusable-password account, leaves public intake disabled, binds the app to a random loopback port and passes operation state through stdin. Secrets remain outside the Docker build context. Successful completion stops only its test containers and retains the volumes; it never deletes volumes or complaints.

This is a small synthetic service-level check inside the Docker application container, not an HTTP/browser load test. Faults are injected at history, receipt, commit and storage boundaries; Docker restart/replacement is performed for real. It does not simulate power loss, process SIGKILL or post-commit callback failures. The E03 snapshot predates current Main integration and PR76 crash reconciliation. A commit-boundary exception is not evidence for the SIGKILL/reconciliation behavior proposed in PR76.

## Validate the recorded report

```bash
python3 docs/evidence/q05-docker-postgresql/verify_report.py
```

## Reproduce from these recorded sources

Start Docker Desktop, then run this from a clone of the repository containing these evidence files. The driver fetches and requires the exact tested E03 branch tip; it refuses a changed branch. It creates a new isolated run, so results will have a new run ID and data digest. The current branch and working files are preserved.

```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

source = Path('docs/evidence/q05-docker-postgresql')
with TemporaryDirectory(prefix='q05-runner-') as directory:
    bundle = Path(directory) / 'runner.zip'
    with zipfile.ZipFile(bundle, 'w') as archive:
        for name in ('run_q05.py', 'probe.py'):
            archive.write(source / name, name)
    exec(compile((source / 'run_q05.py').read_bytes(), 'run_q05.py', 'exec'), {
        '__name__': '__main__', 'BUNDLE_PATH': bundle,
    })
PY
```

Only report.json is shared. Do not commit or upload private.env or private-state.json. The report stores hashes and counts rather than request payloads, credentials, operation keys or raw references.

## Q05 work still pending

- Repeat relevant checks against the final merged application and deployment configuration.
- Verify PR76 crash reconciliation with PostgreSQL after integration.
- Verify real escalation scheduler overlap and interruption/resumption.
- Verify auto-close versus competing feedback.
- Verify actual notification/outbox failure recovery with the F4 owner.

No Jenkins proof or Q04 performance measurements are established by this run. Issue #21 remains open.
