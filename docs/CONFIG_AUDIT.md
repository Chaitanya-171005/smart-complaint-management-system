# Configuration audit contract (B29, REQ-ADM-04, NFR-QUAL-03)

One audit trail for administrative configuration changes, shared by F1 and F3. It answers:
who (Administrator), what (entity), from what to what (old/new values) and when.

## How a module records a change

```python
from accounts.config_audit import record_change
from accounts.models import ConfigAuditEvent

record_change(actor=admin_user, entity_type="SLAConfiguration", entity_id=config.pk,
              action=ConfigAuditEvent.Action.UPDATE, old={...}, new={...})
```

- Call it **inside the same transaction as the change**, after the permission check has already
  passed (check permission *before* opening the transaction, so a refusal's security event is
  not rolled back). A change and its audit record are saved together or not at all.
- `actor` must be a saved `User`. An unknown `entity_type` or `action` raises `ValueError`
  (a programming error caught by tests, never user-triggerable).
- Record only what changed in `old` and `new` (empty `old` for CREATE).

## Shared vocabulary

`entity_type` is the Django model's class name, so both modules use one convention.

| entity_type | Owner | Records |
|---|---|---|
| `Department`, `Location` | F1 | create, edit, deactivate, reactivate |
| `User` | F1 | role and department membership (`role`, `department`) |
| `Category`, `RoutingRule`, `SLAConfiguration`, `EscalationPolicy` | F3 | create, edit, deactivate, reactivate |

Actions: `CREATE`, `UPDATE`, `DEACTIVATE`, `REACTIVATE`. Reference data is never deleted (BR-05).
Adding an entity means adding it to `ENTITY_TYPES` in `accounts/config_audit.py`, which is a
reviewed change.

## Sensitive values

Keys containing `password`, `token`, `secret`, `session` or `reference` are replaced with
`[redacted]` at every depth of a dict or list before storage. Every string value, dict key and
object text also goes through the same `scrub` as the security log
(`accounts.security_log.scrub`), so a secret hiding in an ordinary field such as a description is
replaced too: anonymous references, session keys, digests, other 32+ character token-like runs and
`password=...` style text. Non-JSON values are stored as text. User audit records contain only `role` and `department`, never credentials or contact data.

## Role and membership changes are also security events

`accounts.user_admin_services.set_role_and_membership` writes the configuration audit record **and**
a `SecurityEvent` (`ROLE_CHANGED`, or `ROLE_CHANGE_REFUSED` / `AUTHORIZATION_REFUSED` for refusals,
recorded outside the transaction so they persist). The configuration audit says what changed; the
security log supports security review (REQ-SEC-08).

## Older databases

Before the class-name convention, F1 wrote lowercase entity names (`department`, `location`,
`user`). The table is append-only, so those rows cannot be rewritten. The audit screen therefore
filters entity names case-insensitively, and a database that holds both spellings still shows one
trail. New records always use the class name.

## Not complaint history, and not editable

- `ConfigAuditEvent` is a separate table in `accounts`. It has no link to `workflow.ComplaintHistory`
  and the audit screen never shows complaint content.
- Records are append-only: `save` on an existing record, `delete`, and queryset `update`/`delete`
  all raise. The model is not registered in the Django admin site.
- The only route is the read-only Administrator screen `admin-config/audit/` (GET only, filters by
  entity, action, administrator and date, 50 per page).

## Status

- F1 operations (departments, locations, users) are audited and tested for completeness.
- F3 operations (B17) already call `record_change` with the vocabulary above, and
  `test_every_f3_operation_records_exactly_one_shared_audit_event` checks them.
