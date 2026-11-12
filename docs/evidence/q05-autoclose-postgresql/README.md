# Q05 auto-close versus feedback: local PostgreSQL component evidence

Original local Docker run: 2026-11-11 03:55 UTC, PostgreSQL 17.6, Python 3.14.10, Django 6.1.3. 125 cases passed; zero skipped, failed or errored. This is a separate run from the E03 and B18 evidence in adjacent directories.

Source: draft PR78 at 0a8ddc9db486de97bc010603f5b9124a8c26e200, including PR77 7975360abb7c1ce74856884158199f625f8b7976, checked with Main ebc8ffdf9c1ae37365fad71c084869c73a35b4d0. Clean application tree 65fd8cf0d2b657d780cc94df830c5bd5a82085c0. Application code is unchanged by this evidence commit.

118 existing cases cover auto-close, owner confirmation and rejection; seven added cases exercise actual competing PostgreSQL processes (auto/auto, confirm, reject, maximum reopening), SIGKILL before/after commit, and partial-batch required-history failure/retry. Tests assert history/event/notices/outbox atomicity and preserve F3 assignment/due-time fields. No rating is invented by auto-close.

The seven-day setting is PROPOSED_TEST_SETTING_ONLY, not D05 approval. Durable queued-email writes passed; SMTP delivery and worker retry behavior were not exercised. Real scheduler deployment, anonymous/F3 integration, abandoned B18 run supervision and final merged deployment acceptance remain pending in issue21. These results do not establish Sprint 2 completion or replace Jenkins proof.

Verify: python docs/evidence/q05-autoclose-postgresql/verify_report.py

Reproduce: obtain the pinned app source, verify its Git tree, restore archived sources/*.py.txt to their original paths in a separate working directory, restore Dockerfile, and execute the archived run_task.py through the original Q05_Autoclose_Feedback_Check_20261111.zip. The driver requires unchanged branch tips and emits a new report. Sources are archived with .txt suffixes to prevent accidental pytest collection.

case-results.json is derived from the actual local JUnit file during publication, retaining only case identity, passed outcome and duration, plus original XML SHA-256. It excludes properties and captured output. Original runtime report and harness SHA-256 values are retained unchanged. No private.env, passwords, feedback tokens, or synthetic database rows are published.
