# SCMS setup (E01)

## Run locally
```bash
git clone https://github.com/Chaitanya-171005/smart-complaint-management-system.git
cd smart-complaint-management-system
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # then set DJANGO_SECRET_KEY and DJANGO_DEBUG=True for local work
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
pytest
```
Generate a secret key with:
`python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

## Module ownership (one Django app each)
| App | Area | Owner |
|---|---|---|
| `accounts` | F1 Foundation and Access: users, roles, departments, admin, reports | Anushka |
| `complaints` | F2 Intake and Evidence: complaint form, IDs, evidence, anonymous tracking | Atul |
| `routing` | F3 Routing, Assignment and Escalation: rules, queues, SLA, escalation | Chaitanya |
| `workflow` | F4 Resolution, Notifications and Tracking: lifecycle, history, notices, feedback | Tanmay |

## Contract decisions
- The only user model is `accounts.User` (`AUTH_USER_MODEL`), created before the first migration. Email is the login field. Roles: COMPLAINANT, STAFF, HEAD, ADMIN. `department` is null for Complainants and Admins.
- `Department` lives in `accounts`; other apps reference it with a foreign key (`on_delete=PROTECT`). Master data is deactivated, never deleted.
- Business logic goes in each app's `services.py`, not in templates or views.
- Server-rendered Django templates and forms only: no REST API, no microservices.
- Secrets come from environment variables (`.env`, never committed). `.env.example` lists the names.
- Shared services to be agreed by F1-F4 in follow-up issues: permission checks (B04), history/event recording (B29, Q03), routing hook called by intake (F2 -> F3).
- Tests: pytest with `pytest.ini`; each app keeps `test_*.py` beside its code.
