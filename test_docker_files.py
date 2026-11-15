import http.client
import json
import os
import subprocess
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest
from django.core.handlers.wsgi import WSGIHandler

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
    assert "DJANGO_ALLOWED_HOSTS" in text


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("proxy_https", [False, True])
def test_image_health_command_with_https_redirect(settings, proxy_https):
    settings.SECURE_SSL_REDIRECT = proxy_https
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if proxy_https else None
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    line = next(line for line in read("Dockerfile").splitlines() if line.startswith("HEALTHCHECK "))
    command = json.loads(line.split(" CMD ", 1)[1])
    env = {**os.environ, "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
           "DJANGO_HTTPS_MODE": "proxy" if proxy_https else ""}
    application = WSGIHandler()
    forwarded = []

    def capture(environ, start_response):
        forwarded.append(environ.get("HTTP_X_FORWARDED_PROTO"))
        return application(environ, start_response)

    with make_server("127.0.0.1", 0, capture) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            command[-1] = command[-1].replace("http://127.0.0.1:8000", f"http://127.0.0.1:{server.server_port}")
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert forwarded == ["https" if proxy_https else None]
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("GET", "/accounts/login/", headers={"Host": "localhost"})
                response = connection.getresponse()
                assert response.status == (301 if proxy_https else 200)
                if proxy_https:
                    assert response.getheader("Location").startswith("https://")
            finally:
                connection.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)


def test_compose_security_and_volumes():
    text = read("docker-compose.yml")
    db = text.split("  db:\n", 1)[1].split("  app:\n", 1)[0]
    app = text.split("  app:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert "ports:" not in db
    assert "postgres:17.6" in db and "postgres_data:/var/lib/postgresql/data" in db
    assert "${DJANGO_DB_PASSWORD:?" in db and "pg_isready" in db
    assert "condition: service_healthy" in app
    assert "healthcheck:" not in app  # Compose uses the image's health command.
    assert "image: ${SCMS_IMAGE:-scms-app:local}" in app
    assert "${DJANGO_SECRET_KEY:?" in app and "${DJANGO_DB_PASSWORD:?" in app
    assert "PRIVATE_EVIDENCE_ROOT: /data/private-evidence" in app
    assert "private_evidence:/data/private-evidence" in app
    assert '"127.0.0.1:${APP_PORT:-8000}:8000"' in app
    assert "restart: unless-stopped" in app
    assert "ANONYMOUS_INTAKE_ENABLED: ${ANONYMOUS_INTAKE_ENABLED:-False}" in app
    assert "ANONYMOUS_PRIVACY_READY: ${ANONYMOUS_PRIVACY_READY:-False}" in app
    assert "ANONYMOUS_TRANSPORT_VERIFIED: ${ANONYMOUS_TRANSPORT_VERIFIED:-False}" in app
    assert "DJANGO_HTTPS_MODE: ${DJANGO_HTTPS_MODE:-}" in app
    assert "DJANGO_SECURE_HSTS_SECONDS: ${DJANGO_SECURE_HSTS_SECONDS:-0}" in app


def test_dockerignore_excludes_private_files():
    lines = set(read(".dockerignore").splitlines())
    assert {".env", ".env.*", ".git", "db.sqlite3", "private-evidence"} <= lines
    assert {"**/test_*.py", "**/tests.py", "**/conftest.py", "integration_checks", "scripts/q04_load.py"} <= lines


def test_entrypoint_migrates_before_exec():
    text = read("scripts/docker-entrypoint.sh")
    assert text.startswith("#!/bin/sh\nset -eu\n")
    assert text.index("python manage.py migrate --noinput") < text.index('exec "$@"')


def test_persistence_probe_is_project_scoped_and_uses_disposable_volumes():
    text = read("scripts/verify_docker_persistence.sh")
    assert 'project="scms-e03-persist-' in text
    assert "openssl rand -hex 16" in text
    assert "Generated Compose project already exists; refusing to touch it." in text
    assert "APP_PORT=0" in text
    assert "--force-recreate --wait db app" in text
    assert "--volumes --remove-orphans" in text
    assert 'docker compose -p "$project"' in text
    assert "database-survived-replacement" in text
    assert "evidence-survived-replacement" in text
    assert "docker compose down -v" not in text
