# Official Q04 execution protocol

Status: **NOT RUN**. No timing values are implied by this protocol. Final Main a479551 has a separate healthy loopback preview at http://127.0.0.1:55057, with 650 synthetic records and 550 fresh assignment targets. This is a candidate for an owner-confirmed window, not a measured performance PASS.

## Entry record required before load

Record the approving owner, newly confirmed window start/end/timezone, origin,
final Main SHA, clean tree, deployed image digest, database version/configuration,
worker count, CPU/memory, dataset seed/schema/row counts, network topology/NAT,
ingress limits and background load. Keep credentials, actor cookies and private
references outside Git in restricted private files. Do not reuse an old window
or call the older running preview the final Main deployment.

## Measurements and pass conditions

| Case | Workload | Acceptance | Postcondition/evidence |
| --- | --- | --- | --- |
| Queue | 50 distinct authorized Heads, warmup + 10 measured iterations/user | p95 <=1500 ms, all response/content checks valid | 500 samples, status/error counts, p50/p95/max, <=25 rows/page and page 2 |
| Assignment | Same 50 Heads, 550 unique initially actionable targets including warmups | p95 <=1500 ms, every action successful | Independently verify intended assignee, 550 expected history events, no stale/replayed/duplicate targets |
| Intake/list/detail | 50 distinct authorized actors, fresh intake operation/CSRF per request | p95 <=2000 ms per scenario | Actual accepted graph/ID/receipt, no validation/login response counted as success; list pagination |
| Valid anonymous tracking | 50 genuinely permitted source buckets, one warmup + 9 samples/source | p95 <=2000 ms, all valid restricted lookups | 450 samples, unchanged 10-attempt/10-minute limiter, quarantine respected, no header forgery or allowance reset |
| Escalation | 5000 eligible overdue complaints plus controls on agreed resources | <=60 s | Recorded policy, eligible/examined/escalated/error counts, durable history/outbox, same-time repeat causes no duplicate |
| Report | Owner-provided actual 12-month report on representative data | <=5 s | Correct period/counts and independent expected results; current dashboard is not a substitute |
| Upload | Agreed decimal 5 MB or binary 5 MiB, valid representative content, approved 2 Mbps shaping | <=30 s | Record shaping tool/direction/timer boundaries, original/sanitized bytes, accepted attachment/hash and download authorization |
| Pagination | Inventory all applicable account, staff, notification, history, feedback and report lists | <=25 records/page | Full page, page 2, last page, stable ordering/no duplicate/missing records and authorization filtering |

Use the existing runner, retaining its fixed 50-user barrier, warmup, nearest-rank
percentiles, status/content validation and unfiltered failure timings. Prepare all
targets before timing. Keep warmup dataset changes in the inventory.

Authenticated HTTP command after owner approval:

```sh
python scripts/q04_load.py --config /private/approved-q04.json \
  --actors /private/actors.json --output build/evidence/q04-UNIQUE/report.json
```

The config/actor locations above are placeholders for restricted local files,
not files to commit. Set the approved origin/reference/category/location through
the documented environment variables. Keep real limiter/source behavior intact.
Run the escalation benchmark only against an explicitly owned disposable cluster
and representative approved resources, using `scripts/q04_escalation.py`; retain
its actual measurement scope and exclusions. HTTP_CHECKS_PASS alone does not
constitute a full Q04 pass.

For every run save command, source/image/environment, start/end times, raw numeric
samples, p50/p95/max, error/status counts, validated sample count, database
postconditions, logs and an explicit per-case outcome. For failures, retain the
failed run, remediation source and new-output-path retest. Do not overwrite
targets/reservations or relabel throttling/validation/no-match as successful load.

Current missing items are tracked in the Q04 coordination comment. The reporting
module explicitly lacks D03/B30 period calculations. No application release gate,
privacy control or network exposure should be weakened to fill an evidence row.
