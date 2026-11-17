# Q05 — PostgreSQL SMTP outbox failure and recovery evidence

Atul ran this isolated Docker component check on 12 November 2026 (India),
starting 11 November 2026 at 18:30:30 UTC. All 19 selected cases passed in
21.23 seconds, zero skipped/failed/error cases. Actual runtime: PostgreSQL17.6,
Python3.14.10, Django6.1.3. The report contains the clean tracked application
revision, tree, test hashes, runtime, individual case identities and JUnit hash.

Application: draft F4 PR78 `9b163a24985406d4c00f993bbf2b58e8080cd983`,
including PR77 `cda6fc5e05946d75999ee4f91dd723d571c348a0`.
Git tree: `373d40579d5e96f726990b202dd6c5be6ff04056`.
This records that component revision, not an integration with current Main,
PR71, PR84, or the final deployed application.

## Executed checks

Four existing anonymous SMTP cases cover success on the first, second and third
attempt and exhaustion after three total attempts. Fifteen added cases cover:

- Actual committed owner closure, rating, history and notices survive SMTP
  failures; exact persisted 60/300-second retry boundaries and attempt budget.
- Actual SMTP DATA/recipient 550 rejection, temporary451 refusal, connection
  refusal followed by a fresh process retry, and ambiguous disconnect/timeout.
- Two real PostgreSQL worker processes reserve and send only once.
- Actual SIGKILL after a durable claim or after the local relay accepts data.
- A controlled database-finalization exception after real relay acceptance.
- The actual `deliver_notifications` command and recipient revocation before retry.

Django uses its actual SMTP backend against a synthetic loopback TCP relay
inside the test container. The relay retains synthetic messages in memory;
no real person, mailbox or external SMTP provider is contacted. Clock overrides
exercise due-time and lease boundaries without real waiting. One database-error
case injects an exception; it does not simulate physical database power loss.
Ambiguous SMTP acceptance is UNKNOWN and not blindly resent, so a pass does not
claim exactly-once external mail delivery or guaranteed receipt.

## Evidence and reproduction

`report.json` is the unchanged uploaded report. `case-results.json` is reconstructed
from the original local JUnit only after its SHA256 and the exact 19 case IDs are
verified. All test cases must be passing, and durations must match the report.
No raw JUnit, passwords, SMTP bodies, private.env or private state are published.
Executable harness copies use `.py.txt` so ordinary repository pytest discovery
does not collect these archived component tests.

Validate the recorded artifacts:

```bash
python docs/evidence/q05-smtp-postgresql/verify_report.py
```

To repeat the measurement, obtain the pinned application tree and restore the
four `sources/q05_checks/*.py.txt` files as `q05_checks/*.py`. Run the archived
Docker driver from its original ZIP, or inspect its source for the isolated
PostgreSQL service and local relay configuration. The exact driver hash and
Dockerfile hash are recorded. The existing anonymous test source is
`workflow/test_notification_smtp.py` at the pinned application revision.

## Remaining acceptance

Issue21 remains open for external SMTP/provider/mailbox delivery, final F4/Main
and anonymous privacy integration, deployed worker and scheduler supervision,
D05 policy approval, B18 abandoned RUNNING-run supervision, and final deployment
and power-loss acceptance. This evidence does not enable anonymous intake or
tracking and does not close Q05 or Sprint2.
