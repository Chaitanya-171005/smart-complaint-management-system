# B13 — Restricted reference tracking

Owner: Atul Suresh (F2). Related to #18, #16 and #17.
Requirements: REQ-ANON-03, REQ-SEC-06. Tests: TC-04 and B12 privacy checks.

## User flow

`GET /complaints/track/` shows an empty reference form without login. The reference
is submitted only by a CSRF-protected, same-origin HTTPS POST. A query-string
reference does not perform a lookup. References are never echoed in response
forms, links, cookies or sessions. Lost references remain unrecoverable.

### Route decision relative to SAD section 5

The SAD's conceptual `/anonymous/track/` is implemented as `/complaints/track/`,
with the named route `complaints:track_reference`, to retain the existing F2
complaint namespace. This is an explicit route deviation, consistent with B11's
`/complaints/anonymous/` decision in `B11_ANONYMOUS.md`. No alias exists; an alias
or rename must update the first-position privacy middleware and isolation tests.

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
including IPv4-mapped IPv6. Native IPv6 addresses are grouped by /64 (not /128),
so rotating host addresses within a prefix shares one allowance; IPv4 addresses
use their full address. It uses a separate secret HMAC to derive a transient
Redis key. Stored sorted-set entries contain only server timestamps and random
attempt nonces. Source keys expire no later than 600 seconds after the last
allowed attempt; denied attempts do not extend retention. No IP/source key is
stored in SQL, a complaint, history, a receipt, session, response or application
log. The digest is pseudonymous operational metadata, not a promise of network
anonymity. Users behind the same network source can share the limit.

The Lua prune/count/insert/expire operation is atomic on one shared Redis for
every app process/host. It uses Redis server time. There is no per-process,
Django cache, database, disk or unthrottled fallback. The Lua has a Redis 7 `#!lua` header with no `allow-oom` flag, so the server
refuses it at entry under OOM. This is necessary because a legacy script whose
first write removes expired entries can otherwise continue allocating over
maxmemory. Redis versions below 7 are refused. Memory pressure under
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

1. One dedicated Redis 7+ instance, shared by every app worker, with persistence
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
4. Configure `DJANGO_HTTPS_MODE=direct` only for genuine direct TLS; the limiter
   then uses REMOTE_ADDR and ignores forwarding headers. For nginx/Docker TLS
   termination use `DJANGO_HTTPS_MODE=proxy` and explicit
   `ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS` (comma-separated exact ingress networks,
   never `/0`). Only a peer in those networks may supply the single literal
   X-Real-IP, which nginx MUST overwrite using its observed client address.
   Missing, malformed or untrusted proxy sources fail closed; X-Forwarded-For
   chains are never trusted. The transient source is consumed and scrubbed
   before session/auth/body handling. Never whitelist internet/client networks.
   Campus NAT still groups users sharing one public IPv4 (or IPv6 /64); the app
   cannot recover pre-NAT identities. Deployment must verify acceptable behavior
   with two distinct observed network sources instead of claiming per-person
   fairness. This limitation must be recorded in release acceptance.
5. Serve tracking over HTTPS with the same explicit mode, secure session/CSRF
   cookies, SSL redirection and SecurityMiddleware requirements as B11. E003 and
   the request release predicate enforce these static settings. Proxy mode must
   overwrite X-Forwarded-Proto and preserve the public Host INCLUDING a nondefault
   port (`proxy_set_header Host $http_host`). B12 removes X-Forwarded-Host before
   get_host(), so USE_X_FORWARDED_HOST cannot repair a rewritten Host. Rewriting
   it causes anonymous B11 and B13 same-origin CSRF failure.
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

A successful Redis save/AOF/eviction/slowlog/notification, replication and active
persistence check is cached per client/worker for at most 30 monotonic seconds.
Concurrent requests share that check; no source or reference data is cached.
Failures are never cached as success, expiry rechecks, and Redis command failures
invalidate the cached attestation. The Lua epoch/restart quarantine still runs on
EVERY attempt, including within that cache lifetime. Expected quarantine refusal
retains the configuration cache, preventing repeated CONFIG/INFO round trips.
No per-source allowance is cached locally.

CONFIG GET and INFO remain required: managed Redis services denying them are
unsupported and fail closed. Provision a compatible dedicated service rather
than bypassing safety checks. Runtime administrative changes must be denied by
ACL/operations; the 30-second verification cadence cannot defend against a
privileged operator enabling persistence or capturing memory concurrently.

Configure exact case-sensitive `True` only after those checks:

```dotenv
ANONYMOUS_TRACKING_ENABLED=False
ANONYMOUS_TRACKING_LIMITER_READY=False
ANONYMOUS_TRACKING_REDIS_URL=
ANONYMOUS_TRACKING_SOURCE_SECRET=
ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS=
ANONYMOUS_PRIVACY_READY=False
```

The URL supports redis/rediss, with no query/fragment. Django's deployment check
`complaints.E003` rejects an enabled endpoint with missing static privacy/limiter
configuration. Runtime backend checks refuse unsafe/unavailable services.
Tracking is independently gated from new submissions: disabling intake need
not prevent holders of existing references from checking status.

### Trusted nginx ingress contract

Apply this only inside a reviewed TLS server with restricted backend access:

```nginx
location /complaints/ {
    proxy_pass http://scms_backend;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For "";
    proxy_set_header X-Forwarded-Host "";
}
```

For B13 also enforce a 1 KiB body limit on `/complaints/track/`, and disable/redact
request headers, cookies, body, query and response capture for both anonymous
routes. Adapt the exact location/upstream/certificates in E03/Q02; this snippet
alone is not an approved deployment. If nginx itself is behind another proxy,
its real-IP trust chain needs a separate restricted and tested configuration.

## Real Redis and proxy pipeline

`.github/workflows/b13-redis.yml` starts a dedicated disposable real Redis with
`--save "" --appendonly no --maxmemory 64mb --maxmemory-policy noeviction
--slowlog-log-slower-than -1 --notify-keyspace-events ""`. It runs the full test
suite/coverage through E02, then explicitly executes:

```sh
SCMS_DISPOSABLE_REDIS=True \
SCMS_TRACKING_REDIS_TEST_URL=redis://127.0.0.1:6379/15 \
python -m pytest integration_checks/tracking_redis.py --no-cov -q
```

This integration command requires real Redis, nginx and openssl; missing tools,
unsafe Redis or missing explicit disposable acknowledgement FAIL rather than
skip or use fakeredis. It FLUSHES its disposable test DB and temporarily changes
maxmemory/eviction settings; never point it at shared or production Redis.
Only the default unit suite uses fakeredis.

The real integration checks concurrency, epoch-loss quarantine while the config
check is cached, expiry pruning, /64 grouping, unsafe configuration and OOM.
A real TLS nginx instance proxies two distinct TCP clients (127.0.0.2 and
127.0.0.3) to one Django backend: the first gets ten lookups then 429, while the
second retains its own allowance. Forged X-Real-IP/X-Forwarded-For values are
overwritten. Secure CSRF cookies and Host preservation are exercised through
actual sockets, including B11; a deliberately rewritten Host fails CSRF.

This proves the supplied ingress contract, not an unseen E03 configuration.
E03/Q02 must repeat the two-source/forged-header/Host checks through the actual
deployment and attach evidence before enabling release. A GitHub/Jenkins run
link is required before calling the new workflow executed; committing YAML is
not pipeline-run evidence.

## Verification and remaining acceptance

Original application evidence recorded 991 tests with 70 tracking cases. Review
verification now passes 1,034 default-suite tests with no skips, including 98
tracking cases and 81 anonymous/privacy cases. Every module coverage gate and
Django system/migration check passed. The source used SQLite; deployed
acceptance remains separate.

Run `python -m pytest complaints/test_tracking.py --no-cov -q` for focused tests,
then the shared `scripts/run_tests.py` runner for full module coverage/evidence.
Unit tests execute the production Lua body in fakeredis with Lua support and use the real
Django client, complaint/history tables and CSRF enforcement. They cover the
rolling-window boundary, concurrency, restart quarantine, unsafe configuration,
safe projections, pagination, session isolation and generic errors. Emulator
configuration responses are explicit test doubles, not real Redis proof. The
emulator cannot parse Redis 7 script headers, so only that header is removed in
the unit adapter; the explicit real-Redis tests execute the complete flagged
script, including its OOM behavior.

The nine explicit real-backend/proxy checks passed locally against disposable
Redis 7.4.2 and nginx 1.28.0 over real TLS sockets. This includes entry-time OOM
refusal, concurrency and actual distinct client buckets behind one proxy. The
earlier Redis 6.2 smoke check is superseded: Redis below 7 is now unsupported.
The GitHub workflow is supplied but its hosted run/deployed acceptance remains
pending; no local result is labelled Jenkins/Actions deployment evidence.

Record fresh review evidence under `docs/evidence/b13-review/` only after the
source commit. Preserve the original `b13-tracking` evidence directory. Source
and evidence are separate commits. Keep prior B11/B12 evidence unchanged. SQLite application tests and disposable Redis/proxy checks do not establish
PostgreSQL, hosted Jenkins/Actions, deployed TLS/logging or performance acceptance. Issue #18 remains
open until peer review/merge and the deployment/history checks are completed.
This does not close #16/#17 or introduce reference recovery or feedback.

Algorithm/configuration references: Redis's official
[rolling-window examples](https://redis.io/docs/latest/develop/use-cases/rate-limiter/redis-py/),
[persistence guidance](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
and [eviction policies](https://redis.io/docs/latest/develop/reference/eviction/) and
[Lua script flags](https://redis.io/docs/latest/develop/programmability/lua-api/).


## Merge order

This review incorporates #71 through its `d9b231e` review-evidence commit. Keep
#73 draft and based on #71 until #71 is approved and merged. Then update/rebase
against Main, retarget to Main, confirm the intended diff, rerun verification and
record new clean-source evidence. Do not claim deployment/history acceptance or
close #18 from this source change alone.
