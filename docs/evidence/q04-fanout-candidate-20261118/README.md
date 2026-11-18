# Q04 remediation candidate — no new load result

Source `3ace587ca046080f30fa2a554362048237bcb100` is based on Main
`a479551c61beb2e2f6e04b93b167084bb7397dcc`, separate from the Q06/UI branch.
Related defect: #102. This candidate is proposed for genuine owner review; it
neither closes the defect nor proves the 1.5-second target.

An actual single-action SQL probe with 50 synthetic department Heads found 52
notification INSERTs plus 52 email-job INSERTs, 114 SQL statements total. The
same correctness probe after batching found one INSERT per table, 13 statements
total, with the exact same 52 eligible recipients, pending jobs, history/event
and idempotent replay. With three Heads the counts changed from 20 total / ten
INSERTs to 13 total / two INSERTs. These are **single-action query counts**, not a
50-concurrent-user load benchmark or timings.

The new regression fails twice before the fix and passes after it. Actual
focused result: **414 passed, zero failed/errors/skipped**, covering notification
channels/recipients, idempotence, privacy, permission changes, intake, resolution,
feedback, reopening, confirmation, auto-close, and transaction rollback. Existing
failure injections now target the actual bulk write points. No model save hooks
or signals existed for these outbox models. History still uses its validated
single-row writer; no history bulk-create restriction is bypassed.

Notification recipient authorization/projection and the atomic business
transaction/locks are unchanged. No conflicts are ignored. Failure of either
required table insert rolls back the assignment/history/event graph. Email IDs
are read back from the newly created event, so backend-specific bulk PK return
behavior is not required. SMTP remains deferred to its existing outbox worker.

The isolated **q04/compose.yml only** now requests four Gunicorn sync workers,
one thread each, instead of its previous implicit single worker. This is a
second, explicitly recorded resource change. Any future timing comparison must
state both code and worker changes, not attribute all improvement to batching.
No production Compose default, authorization, limiter, release gate or coverage
threshold was changed.

Preparation of the new task-owned Docker project stopped because Docker Desktop
is manually paused. `prepare-stack.txt` is the actual failed preparation log;
no candidate image or new concurrent load result exists yet. The earlier load
window expired at 21:30 IST on 18 November. A new explicit window is required;
elapsed time or silence is not consent. No previous measured failure is relabelled.

Last real authorized result remains queue p95 2,895.659 ms and assignment p95
7,147.723 ms, both failing <=1,500 ms. Preserve its original packet on PR #101.
Other Q04 scenarios and final Main/Q05/human acceptance remain separate pending
work. See REPRODUCE.md for actual focused commands and the guarded next run.
