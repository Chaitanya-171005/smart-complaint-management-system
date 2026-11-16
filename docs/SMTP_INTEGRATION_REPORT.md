# SMTP candidate verification — 2026-11-16

Implemented in a separate worktree `/tmp/scms-smtp-candidate`, branch
`integration/smtp-env-20261116`, based on exact F3 candidate
`7b0a6bf15bdc8056eaf0de659e76ede31858ea95`. Repository backing this worktree:
`/tmp/scms-pr82-f3-isolated`. Tested implementation commit:
`ddd3725695485ff10f39ad2b7109e894227a4f37`. The report commit adds documentation only.

## Changes

- `scms/mail_config.py`: pure environment parser using Django 6.1 MAILERS;
  encrypted SMTP, host/port, credential pairing, sender, timeout and strict
  transport validation. Uses Django's verified SSL context, no insecure bypass.
- `scms/settings.py`: retains console default and configures MAILERS plus
  DEFAULT_FROM_EMAIL. Does not enable release flags or change web protections.
- `docker-compose.yml`: forwards nine mail variables to app only.
- `.env.example`, `.env.docker.example`: console defaults and empty secret fields.
- `scms/test_mail_config.py`: 37 deterministic cases; SMTP transport and hostname
  lookup mocked for delivery tests. Development console, authenticated/encrypted
  delivery, invalid settings, certificate, timeout, connection, TLS, authentication
  and send failures verified. No real mail or SMTP service contact.
- `.coveragerc`: includes the SMTP parser alongside existing F1–F4 coverage.
- `docs/SMTP.md`, `docs/E03.md`: setup, secret handling and controlled-delivery
  procedure for later authorized verification.

## Results

| Check | Exact result |
| --- | --- |
| Final focused SMTP, foundation and anonymous escalation contract checks | 51 passed in 1.41s |
| SMTP-only tests | 37 passed in 0.11s |
| Full regression on clean implementation commit | 1,238 passed, 2 failed, 13 setup errors in 38.67s |
| SMTP parser coverage | 45/45 statements, 20/20 branches; 100% each |
| Coverage gates | All four module gates PASS |
| Django system check | No issues, 0 silenced |
| makemigrations --check --dry-run | No changes detected |
| Fresh candidate SQLite migrations and migrate --check | Applied successfully; check exit 0 |
| Docker Compose config --quiet with synthetic values | Exit 0; no containers started |
| Synthetic production manage.py check --deploy | Exit 0; two warnings, listed below |
| git diff --check | Passed |

| Module | Line | Branch |
| --- | ---: | ---: |
| accounts | 98.51% | 96.79% |
| complaints | 98.32% | 96.59% |
| routing | 93.77% | 85.15% |
| workflow | 92.73% | 95.00% |

Full verification used the existing virtual environment Python with a test-only
secret and SQLite, invoking `scripts/ci_checks.sh build/evidence/smtp-final`.
The runner records pytest exit 1 and gate exit 0; this is not a green full suite.
Evidence remains in `build/evidence/smtp-final/` and `coverage.json`.
Focused checks explicitly include `integration_checks/anonymous_escalation.py`.

All 15 non-passing full-suite cases fail at socket.bind with
`PermissionError: [Errno 1] Operation not permitted`: two image-health server
tests and thirteen Q04 HTTP fixture tests. These are the same environment
restrictions independently reproduced on unchanged Main during F3 verification;
the affected test files, Dockerfile and Q04 implementation are unchanged here.
No unrelated tests were skipped, weakened or modified. PostgreSQL-specific
verification remains subject to the prior sandbox shared-memory restriction;
existing Docker/PostgreSQL resources were not used to bypass it.

## Deployment warnings and dependencies

Synthetic deployment checks selected SMTP using reserved `.test` addresses,
synthetic credentials, a random test secret, DEBUG=False, allowed hosts,
HTTPS redirect, secure session/CSRF cookies, direct HTTPS topology and one-year
HSTS. The check does not send email or contact SMTP. Remaining warnings:

- security.W005: SECURE_HSTS_INCLUDE_SUBDOMAINS is unset.
- security.W021: SECURE_HSTS_PRELOAD is unset.

These require deployment-owner decisions about all subdomains and browser
preloading; no protection was weakened or warning silenced. No real production
credential or domain policy was invented.

Before deployment, obtain provider credentials, approved sender/domain, DNS
authentication and trusted CA configuration where needed; verify network egress
and an actual approved controlled delivery using docs/SMTP.md. Console remains
the default even with DEBUG=False, so operators must deliberately select smtp.
F4 notification routing, safe anonymous projection, outbox/retries and delivery
acceptance remain separate work. Backend failures propagate rather than silently
dropping mail; notification consumers must handle them without logging secrets.

Original checkout remains at `777c515c7448f5d5d4670c75498f6b12c3f7c2e3` with the
same untracked `.env.docker`, `build/`, and Q04 readiness evidence directory. The
F3 candidate remains clean at its original commit. No existing Docker resources,
Q04 reservations, contributor branches or local environment files were changed.
Nothing was pushed or merged into Main.
