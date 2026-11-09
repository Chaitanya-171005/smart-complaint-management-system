from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return (ROOT / name).read_text()


def test_dockerfile_runtime_and_build_secrets():
    text = read("Dockerfile")
    lines = text.splitlines()
    assert "FROM python:3.14-slim" in lines
    assert "USER appuser" in lines
    assert "COPY requirements.txt /app/requirements.txt" in lines
    assert "requirements-dev.txt" not in text
    assert not any(line.strip().startswith(("ENV ", "ARG ")) and "SECRET_KEY" in line for line in lines)
    secret_lines = [line for line in lines if "DJANGO_SECRET_KEY" in line]
    assert len(secret_lines) == 1 and secret_lines[0].startswith("RUN DJANGO_SECRET_KEY=")
    assert "collectstatic --noinput" in secret_lines[0]
    assert not any(line.strip().startswith("COPY ") and ".env" in line for line in lines)
    assert "HEALTHCHECK" in text and "/accounts/login/" in text


def test_compose_security_and_volumes():
    text = read("docker-compose.yml")
    db = text.split("  db:\n", 1)[1].split("  app:\n", 1)[0]
    app = text.split("  app:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert "ports:" not in db
    assert "postgres:17.6" in db and "postgres_data:/var/lib/postgresql/data" in db
    assert "${DJANGO_DB_PASSWORD:?" in db and "pg_isready" in db
    assert "condition: service_healthy" in app
    assert "${DJANGO_SECRET_KEY:?" in app and "${DJANGO_DB_PASSWORD:?" in app
    assert "PRIVATE_EVIDENCE_ROOT: /data/private-evidence" in app
    assert "private_evidence:/data/private-evidence" in app
    assert "${APP_PORT:-8000}:8000" in app


def test_dockerignore_excludes_private_files():
    lines = set(read(".dockerignore").splitlines())
    assert {".env", ".env.*", ".git", "db.sqlite3", "private-evidence"} <= lines


def test_entrypoint_migrates_before_exec():
    text = read("scripts/docker-entrypoint.sh")
    assert text.startswith("#!/bin/sh\nset -eu\n")
    assert text.index("python manage.py migrate --noinput") < text.index('exec "$@"')
