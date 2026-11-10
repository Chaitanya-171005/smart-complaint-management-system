# B13 — Restricted reference tracking

Owner: Atul Suresh (F2). Related to #18, #16 and #17.
Requirements: REQ-ANON-03, REQ-SEC-06. Tests: TC-04 and B12 privacy checks.

## User flow

`GET /complaints/track/` shows an empty reference form without login. The reference
is submitted only by a CSRF-protected, same-origin HTTPS POST. A query-string
reference does not perform a lookup. References are never echoed in response
forms, links, cookies or sessions. Lost references remain unrecoverable.

A valid reference shows only complaint ID, category, location, current status,
escalation flag and permitted status history. It does not authorize the full
record, acknowledgement, attachments, feedback or other actions. A complaint ID
alone authorizes nothing. Malformed and unknown references have the same 200
no-match page and one indexed anonymous-record query. This is response/query
shape consistency, not a claim of constant-time HTTP/database execution.

History comes from F4's `get_complaint_history` and contains only timestamps,
known event labels and known previous/new status labels. Actor identities,
assignees and free-text remarks are excluded. Unknown event/state values are
excluded. The latest history page is first; entries within a page are in time
order. Pages contain at most 25 entries. To view another page, re-enter the
reference and page number; the credential is never carried in a pagination URL
or hidden input. Each page lookup consumes an attempt. F4 must review this
projection as its lifecycle/history schema evolves.

POST transport accepts at most 1,024 declared body bytes in URL-encoded form;
multipart uploads and oversized requests are refused before parsing. The
reverse proxy must enforce a real request-body limit, including streamed input;
the application's Content-Length check alone is not that network boundary.

## Shared rolling limit

All tracking POSTs that reach the enabled endpoint consume one allowance before
CSRF/body validation or complaint lookup. Successful, malformed and unknown
lookups share the same allowance: at most ten in `(now - 600 seconds, now]`.
The eleventh returns 429 with Retry-After; it performs no complaint query.
GET/unsupported methods do not consume lookup allowances. A failed prerequisite,
backend error or missing peer address returns 503 and grants no lookup.

`complaints.tracking_limits.consume_attempt` accepts only the request peer IP.
It accepts no account, complaint or reference argument. It normalizes IPs,
including IPv4-mapped IPv6, and uses a separate secret HMAC to derive a transient
Redis key. Stored sorted-set entries contain only server timestamps and random
attempt nonces. Source keys expire no later than 600 seconds after the last
allowed attempt; denied attempts do not extend retention. No IP/source key is
stored in SQL, a complaint, history, a receipt, session, response or application
log. The digest is pseudonymous operational metadata, not a promise of network
anonymity. Users behind the same network source can share the limit.

The Lua prune/count/insert/expire operation is atomic on one shared Redis for
every app process/host. It uses Redis server time. There is no per-process,
Django cache, database, disk or unthrottled fallback. Memory pressure under
noeviction fails closed. Timeout retries are disabled: an ambiguous command
failure returns unavailable rather than pretending no attempt happened.

A non-identifying global `scms:b13:epoch` timestamp is created atomically on the
first tracking POST after Redis starts or loses all state. All lookups remain
unavailable for 600 seconds from that first POST, preventing a restart from
resetting a source's allowance inside an earlier window. That global timestamp
has no source/reference/complaint data. Do not manually predate, reset, delete
or restore limiter keys to bypass this quarantine.

## Deployment configuration — disabled by default

This application change does not provision or approve a deployed Redis service.
E03/F3 must provide and verify the following before enabling it:

1. One dedicated Redis instance, shared by every app worker, with persistence
   disabled (`save ""`, `appendonly no`), no replicas, a positive maxmemory and
   `maxmemory-policy noeviction`. It must not use a persistence-enabled general
   application cache, managed-service backups, disk tiering or snapshot restores.
2. Disable command/slow-query recording (`slowlog-log-slower-than -1`) and
   keyspace notifications (`notify-keyspace-events ""`). Forbid MONITOR,
   manual SAVE/BGSAVE, FLUSH and runtime configuration changes for the app user.
   Restrict other users/operators and monitoring tools accordingly. Keep host
   swap, core dumps, memory snapshots/hibernation and packet capture from
   persisting source metadata. Redis configuration checks cannot verify these
   host/operator safeguards.
3. Use an internal authenticated connection (TLS when crossing an untrusted
   network), restricted ingress/ACLs and controlled server clocks. The app user
   needs CONFIG GET, INFO, EVAL, TIME, GET, SET, ZREMRANGEBYSCORE, ZCARD, ZRANGE,
   ZADD and EXPIRE for the `scms:b13:*` namespace, plus connection commands.
   It does not need administrative write, snapshot, tracing or FLUSH permissions.
   App Redis URL query overrides are rejected. URL credentials belong in secrets
   management and must never appear in committed evidence.
4. Establish the request source in the trusted WSGI/ingress boundary's
   REMOTE_ADDR. The app deliberately ignores X-Forwarded-For and similar client
   headers. Only accept rewritten peer addresses from a trusted proxy; never
   let an internet client choose REMOTE_ADDR. If all requests appear as one
   proxy address, they share one limit; fix/verify the ingress before release.
5. Serve tracking over HTTPS with correct trusted proxy/TLS configuration.
   Disable/redact access query/body/header logs, SQL/debug logs, APM request
   capture, error emails and response capture on this route. First-position B12
   privacy middleware strips session/account cookies, source/identity headers
   and query strings after the source allowance is consumed. Anonymous forms
   accept same-origin requests only; invalid Host/Origin/Referer refusals avoid
   logging raw attacker-supplied header values. This does not
   erase data already captured by infrastructure outside Django.
6. Keep the same randomly generated source secret (at least 32 characters)
   across all workers, separate from the Django secret. Coordinate rotation
   with a full ten-minute tracking outage; changing it live creates new keys.
7. Verify all-worker 10th/11th-attempt behavior, TTL removal, Redis outage/OOM,
   a full restart quarantine, safe logs and denied full-record/evidence access
   with synthetic data. F4 reviews permitted history; B12 owners review their
   affected integrations. Record actual environment and results.

Every lookup checks Redis save/AOF/eviction/slowlog/notification settings,
replication and active persistence state before writing a source key. Forbidden
or unreadable configuration fails closed. These checks complement the required
deployment review; they cannot stop a privileged operator from changing Redis
or capturing memory concurrently.

Configure exact case-sensitive `True` only after those checks:

```dotenv
ANONYMOUS_TRACKING_ENABLED=False
ANONYMOUS_TRACKING_LIMITER_READY=False
ANONYMOUS_TRACKING_REDIS_URL=
ANONYMOUS_TRACKING_SOURCE_SECRET=
ANONYMOUS_PRIVACY_READY=False
```

The URL supports redis/rediss, with no query/fragment. Django's deployment check
`complaints.E003` rejects an enabled endpoint with missing static privacy/limiter
configuration. Runtime backend checks refuse unsafe/unavailable services.
Tracking is independently gated from new submissions: disabling intake need
not prevent holders of existing references from checking status.

## Verification and remaining acceptance

Local application verification: 991 tests passed without skips, including 70
new tracking cases; every module coverage gate passed. Django system/migration
checks were clean. The source used SQLite; deployed acceptance remains separate.

Run `python -m pytest complaints/test_tracking.py --no-cov -q` for focused tests,
then the shared `scripts/run_tests.py` runner for full module coverage/evidence.
Tests execute the production Lua in fakeredis with Lua support and use the real
Django client, complaint/history tables and CSRF enforcement. They cover the
rolling-window boundary, concurrency, restart quarantine, unsafe configuration,
safe projections, pagination, session isolation and generic errors. Emulator
configuration responses are explicit test doubles, not real Redis proof.

An additional isolated local Redis 6.2.14 smoke check verified initial quarantine,
exactly ten allowances across 24 concurrent calls, bounded source-set size/TTL
and refusal after enabling snapshot configuration. It used synthetic source
data and a disposable instance; this is not evidence for the E03 deployment.

Record clean-source evidence under `docs/evidence/b13-tracking/` only after the
source commit. Source and evidence are separate commits. Keep prior B11/B12
evidence unchanged. SQLite application tests do not establish PostgreSQL,
Jenkins, real Redis, TLS/logging or performance acceptance. Issue #18 remains
open until peer review/merge and the deployment/history checks are completed.
This does not close #16/#17 or introduce reference recovery or feedback.

Algorithm/configuration references: Redis's official
[rolling-window examples](https://redis.io/docs/latest/develop/use-cases/rate-limiter/redis-py/),
[persistence guidance](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
and [eviction policies](https://redis.io/docs/latest/develop/reference/eviction/).
