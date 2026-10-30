# Reference data administration (B05, REQ-ADM-01, BR-05)

Owner: F1 (departments and locations). Categories, routing and SLA stay with F3 (B17).

## Rules
- Only the Administrator may create, edit, deactivate or reactivate departments and locations
  (`can_manage_configuration`). Other roles get 403; anonymous users go to login. Refusals are
  security events and the refused change leaves no trace.
- Reference data is **deactivated, never deleted**: `delete()` on a record or a queryset raises.
  Inactive records stay on existing users and complaints.
- New operations must choose from `reference_services.active_departments()` and
  `active_locations()`. Do not query `Department`/`Location` directly for a selector.
- Every change writes a `ConfigAuditEvent` (acting Admin, entity, old/new values, time) in the
  same transaction as the change. See `accounts/config_audit.py`; B29 extends this to F3.

## Field limits (SRS Appendix B)
| Entity | Field | Limit |
|---|---|---|
| Department | name | 50, unique ignoring case |
| Location | code | 100, stable key, stored as `strip().upper()` (same as B17 `location_code`), unique |
| Location | block / floor / room_area | 20 / 10 (optional) / 30; the combination is unique ignoring case |

The location **code is never edited** after creation: other modules store and route on it.

## Contract for other modules
- **B07 (intake form):** build `LocationOption(key=code, block=block, room_area=room_area, floor=floor,
  active=active)` from `Location`, passing only active rows. No adapter is included here because
  `complaints.reference_data` is in an unmerged PR.
- **B17 (routing):** a routing rule's `location_code` must match an existing `Location.code`, and a
  rule should not target an inactive department. B17 does not check this yet; to agree with
  Chaitanya. Categories also need a 50-character name limit to match B07.
- **B06 (users):** department membership choices come from `active_departments()`.
- **B29 (audit):** call `record_change(...)` inside the same transaction for F3 category, routing
  and SLA changes; sensitive field names are replaced by `[redacted]`.

## Open points
- D01: no campus departments, locations or codes are seeded. The Administrator enters the
  confirmed values; tests use synthetic names only.
- Deactivating a department that active routing rules or active Staff still use is allowed here
  (existing references must be preserved). Whether to warn or block is for the team to decide.
