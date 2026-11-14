# Q04 isolated Docker setup (work in progress)

This creates a separate local Docker Compose project, not a production deployment. The runner must not be used without the test owner's approval. The current implementation remains experimental: review the limitations below before relying on it.

## Prerequisites and setup

Install Git, Python 3.10 or later, Docker Desktop (macOS/Windows), or Docker Engine with the Compose v2 plugin (Linux). Start Docker. Clone this repository and check out the revision under test. On macOS or Ubuntu, run:

```sh
git clone https://github.com/Chaitanya-171005/smart-complaint-management-system.git
cd smart-complaint-management-system
git switch feature/Q04-portable-environment
python3 scripts/q04_env.py up
```

On Windows PowerShell, use `py -3 scripts/q04_env.py up` after cloning and entering the directory. Python's normal installation and Docker access are required. These Windows and Linux instructions have not yet been verified.

The default URL is http://127.0.0.1:55004. Set a different available port on the initial setup with `python3 scripts/q04_env.py up --port 55017`; `--complaints 650` controls synthetic dataset size (minimum 600). The first setup generates project-scoped credentials and a unique Compose project. Files are stored under `~/.scms-q04/<checkout-hash>` outside the repository; do not share them publicly or commit them. Unix files are mode 0600; Windows users must ensure their profile directory's ACL restricts access. The app is bound to loopback; PostgreSQL has no published port. Separate project-scoped named volumes hold database and private evidence. The E03 entrypoint runs migrations on app startup.

`python3 scripts/q04_env.py status`, `check`, `seed`, and `down` show status, perform read-only HTTP checks, rerun seeding, and stop/remove only the Q04 project's containers and network respectively. `down` retains the Q04 volumes. Repeated setup reuses the project's settings and data. Do not manually delete volumes belonging to other projects. Reset requires `reset --confirm --project PROJECT` using the exact project from `config`. It verifies both volume ownership labels before requesting Compose removal. Reset deletes that project’s data; do not use it on an environment whose data must be preserved.

The seed uses synthetic users and test records; it prepares 50 heads, 50 complainants, two eligible staff, 550 unique assignment targets and additional queue data. Sessions are created using the actual CSRF-enforced Django login view and stored privately. Rerunning the seed regenerates sessions and leaves existing complaints intact, including consumed targets. Initial credentials are generated once per environment. The configuration and dataset are synthetic; no real identity or production data is required.

## Benchmark and known limitations

Do not run a load test without express authorization. The current prototype offers `python3 scripts/q04_env.py run --confirm`; it checks head sessions, reserves one set of 550 distinct targets, and refuses a second run using the same set. This code path has not been verified against a real 50-user run. A single disposable assignment was smoke-tested separately with one allocation history event. Queue and assignment are the only enabled scenarios, so the overall Q04 result remains incomplete. The existing Q04 runner records status, latency, p95, errors and metadata. It reports the checkout's HEAD even if files are uncommitted; retain a separate accurate record of the tested image and worktree state. The 550 targets permit exactly one default warmup plus ten samples per head. Do not remove the reservation marker or reuse consumed records. The prototype has not established safe multi-process concurrent invocation or regenerated fresh targets after consumption.

Intake is intentionally disabled by its release gate; anonymous intake and its privacy/transport controls remain disabled. Tracking, complainant list/detail and 12-month reporting are not available in the referenced deployment. Successful acknowledgement and evidence upload/download have not been verified. An escalation command exists but the 5,000 eligible overdue records required for Q04 are not prepared. D02's exact 5 MB upload convention and approved network shaping remain open. No latency or performance acceptance is implied by startup checks.

## Sharing access

The loopback address is reachable only on the host computer. Prefer that each developer run a separate environment. Sharing requires a separately approved private network and a reviewed HTTPS reverse proxy, firewall allowlist, host validation, CSRF trusted origins, and authentication; no public binding or proxy trust should be enabled merely for testing. This prototype does not configure or verify ZeroTier, external bind addresses, TLS or trusted proxies. Do not use it as instructions to expose a service publicly. Transfer synthetic credentials only through an approved private channel.

## Troubleshooting and comparison

If a port is occupied, choose another port during the first setup. For an existing environment, `status` identifies the project and `down` stops its containers without deleting volumes. Check Docker availability and Compose version if startup fails. Never post the settings or actor files when requesting help. Record the exact built source revision and dirty state, image identity, host resources, app worker count, PostgreSQL configuration, network, dataset, warmup and measurement settings when comparing runs; loopback timings are not production acceptance.

### Current implementation status

The initial `up` accepts `--random-seed INTEGER` and `--complaints COUNT`; their values and the port are fixed in local private settings and subsequent conflicting options are refused. Seeded priorities and department placement use a deterministic hash, and rerunning the seed retains previously created complaints and assignments. The first 550 targets belong to the head's department; additional new records are distributed between two synthetic departments. Existing data created by an older prototype is retained, so this does not retroactively make older datasets reproducible.

The readiness checker consults application settings before labeling a 503 as `RELEASE_GATED`; an unexpected 503 is `FAILED`. Assignment, evidence and the escalation command are reported as `NOT_VERIFIED` unless separately checked. A confirmed reset verifies both Q04 volume labels and is serialized with lifecycle commands; its destructive Docker path was exercised on one disposable macOS project; broader platform and failure-case validation remains pending. A run reserves its targets atomically before preflight. Reservation is deliberately retained on failure or interruption; only a confirmed preflight reservation can be recovered with `recover --confirm`; a running or unknown reservation requires investigation. Do not delete that marker to force a rerun, because the prior run might still be active or targets might have been consumed. Benchmark execution is not yet approved for production use.

### Named environments and legacy settings

Inspect non-secret settings with `python3 scripts/q04_env.py config`. If `seed_recorded` is false, seed 0 is a compatibility default; it does not establish the historical seed used to create existing records. Reuse an existing environment without changing its settings with `python3 scripts/q04_env.py up`. Create a different isolated project with `python3 scripts/q04_env.py up --environment seed42 --port 55037 --random-seed 42`. Supply the same `--environment` option to its other commands. Do not use a port already occupied by another service.

Lifecycle operations use an operating-system lock scoped to the named environment. Benchmark reservation is retained when a run starts, fails or is interrupted. Use `recover --confirm` only to clear a preflight-only reservation. A running or unknown reservation requires investigation of the process and targets; do not delete it to force a rerun. The full benchmark path remains unverified, and Windows and Linux locks have not been tested. A macOS disposable-project reset removed only its two owned volumes in one observed test.

### Run-state records and session reuse

A Q04 run reserves its targets with a unique run identifier and records its phase and state (`preflight`, `running`, `failed`, `interrupted`, or `completed`). An interrupt or failure after execution starts leaves the reservation in place: a process or requests may still have changed records. Investigate the saved state, runner processes, result and database targets manually; do not delete the reservation to bypass this check. `recover --confirm` clears only a preflight reservation, because no benchmark was launched at that phase. A hard process kill may leave the last state as `running`; treat it as potentially mutating.

`up` checks the existing role sessions and reuses them when valid and the expected dataset count is present; otherwise it runs the idempotent seeder and refreshes sessions. The environment lock serializes the provided lifecycle commands. It cannot prevent direct Docker or database commands outside this tool, so do not use those concurrently. A reset checks both volume labels and requires the exact configured project name; it is destructive to that named project's data and must be separately authorized.

### Build troubleshooting

An earlier `collectstatic` build failed while tests were running, but its detailed error was not retained, so its cause is unknown. The image runs `collectstatic` inside the image layer at `/app/staticfiles`; host `staticfiles` and SQLite database sidecars are excluded from the build context. Check Docker's build output and available disk and memory before retrying. Cached build successes do not prove that the static collection step executed. Preserve sanitized logs when investigating failures.

Reset refuses when the set of volumes labeled for the project differs from the two expected Q04 volumes, including when an additional labeled volume exists. Investigate the ownership mismatch; do not relabel or remove a volume simply to make reset pass. Locally captured adversarial probes and build logs should remain outside the repository unless reviewed for secrets.

For an unresolved run, inspect the private `action-targets-consumed` state file in the private environment directory shown by `up` to obtain its `run_id`, state and phase. The associated private `actors.json` lists each action target; the current default set is `SCMS-2099-000001` through `SCMS-2099-000550`. Preserve both files and any runner report while checking the relevant assignments and history. Do not publish their contents: actor files contain session credentials. A failed or interrupted reset can have removed some resources; inspect the actual project containers and labeled volumes before taking action. A reset retry refuses if the expected volume set is incomplete.
