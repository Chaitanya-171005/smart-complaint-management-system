# Security logging policy (Q03, REQ-SEC-08)

Security events answer: **who** did **what** to **which target**, and **when**. They help review
logins, refusals and administrative changes. They never hold secrets or link to an anonymous reporter.

## How a module records an event

Always through `accounts.security_log.record_event`; never create `SecurityEvent` rows directly.

```python
record_event(SecurityEvent.EventType.AUTHORIZATION_REFUSED, user=actor, identifier=actor.email,
             target="Complaint#12", detail="can_view_complaint")
```

| Field | Meaning |
|---|---|
| `event_type` | The action. One of the fixed `SecurityEvent.EventType` values; an unknown value raises `ValueError`. |
| `user` / `identifier` | The actor. `user` is empty for unauthenticated and anonymous actors; `identifier` is the sign-in email (or what was typed at login) and is empty for anonymous actors. |
| `target` | What was acted on, as `ModelName#id` (for example `Department#4`). |
| `detail` | Short context, such as the permission check that refused or `role COMPLAINANT->STAFF`. |
| `created_at` | Set by the database when the event is written. |

## Events required by REQ-SEC-08

| Event type | Raised by | Notes |
|---|---|---|
| `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGIN_LOCKOUT`, `LOGIN_BLOCKED` | B02 login | Same result for a wrong password and an unknown email. |
| `AUTHORIZATION_REFUSED` | B04 permission helpers (every module) | Actor, the failed check and the target object. |
| `ROLE_CHANGED`, `ROLE_CHANGE_REFUSED` | B06 role and membership changes | Old and new role in `detail`. Refusals are logged outside the transaction so they persist. |
| `MASTER_DATA_CHANGED` | `record_change`, for every F1 and F3 configuration change except role changes | One consistent event: actor, `Model#id` target, action (`CREATE`, `UPDATE`, ...). Written in the same transaction as the change, so a rolled-back change leaves no event. |

Module owners add an event type to `SecurityEvent.EventType` (a reviewed change) rather than
inventing free-form events. F2 and F4 supply their events through the same function.

## Never logged

- Passwords, password hashes and session keys.
- Anonymous complaint references, their digests, and anything that links an anonymous report to a person.
- Request bodies, query strings and file content.

`record_event` enforces this even if a caller makes a mistake: free text and identifiers are
scrubbed (an identifier is kept verbatim only when it is exactly the acting user's own saved email;
what was typed at login is untrusted, even when it contains an "@"), replacing any 32+ character token-like run (a reference, a session key, a digest) and
any `password=...` / `token: ...` style assignment with `[redacted]`. Anonymous actors are recorded
with no user and no identifier. The configuration audit (`ConfigAuditEvent`) applies the same `scrub` to every string value, key
and object text at any depth, and also replaces values stored under sensitive key names (B29).

## Not editable

`SecurityEvent` is append-only: saving an existing row, deleting, and queryset `update` / `delete`
all raise. Retention and review procedures are out of scope here and need team confirmation.

## Where this is tested

`accounts/test_security_log.py` triggers each required event, checks the actor/action/target/time
fields, sweeps both stores for a known password, session key and anonymous reference after realistic
scenarios, and checks the append-only and unknown-event rules. Other modules add their own events to
this policy and a test beside the code that raises them.
