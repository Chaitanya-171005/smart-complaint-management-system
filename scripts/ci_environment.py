"""Read-only CI preflight: syntax, Compose and synthetic deployment settings."""
import compileall
import os
from pathlib import Path
import secrets
import subprocess  # nosec B404 - fixed CI commands, never request input
import sys

ROOT = Path(__file__).resolve().parent.parent


def commands():
    return [
        ["docker", "compose", "--env-file", "/dev/null", "--file",
         str(ROOT / "docker-compose.yml"), "--profile", "scheduled", "config", "--quiet"],
        [sys.executable, "manage.py", "check", "--deploy"],
    ]


def synthetic_environment(environ):
    env = dict(environ)
    # No production settings or SMTP credential is needed by this preflight.
    for name in list(env):
        if name.startswith(("DJANGO_", "RECOVERY_POSTGRES_", "DJANGO_SMTP_")):
            env.pop(name)
    env.update(DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DJANGO_DEBUG="False",
               DJANGO_SETTINGS_MODULE="scms.settings", DJANGO_DB_ENGINE="sqlite",
               DJANGO_DB_PATH=str(ROOT / "build/ci-deploy.sqlite3"),
               DJANGO_ALLOWED_HOSTS="scms.example.test", DJANGO_DB_NAME="synthetic",
               DJANGO_DB_USER="synthetic", DJANGO_DB_PASSWORD="synthetic-only",
               DJANGO_MAIL_BACKEND="smtp", DJANGO_SMTP_HOST="smtp.example.test",
               DJANGO_DEFAULT_FROM_EMAIL="scms@example.test", DJANGO_SMTP_USE_TLS="True",
               DJANGO_SMTP_USE_SSL="False", DJANGO_SECURE_SSL_REDIRECT="True",
               DJANGO_SESSION_COOKIE_SECURE="True", DJANGO_CSRF_COOKIE_SECURE="True",
               DJANGO_HTTPS_MODE="direct", DJANGO_SECURE_HSTS_SECONDS="31536000",
               ANONYMOUS_INTAKE_ENABLED="False", ANONYMOUS_PRIVACY_READY="False",
               ANONYMOUS_TRANSPORT_VERIFIED="False", COMPLAINT_INTAKE_ENABLED="False")
    # Never load a developer's private Compose env file.
    env["COMPOSE_ENV_FILES"] = "/dev/null"
    env["COMPOSE_DISABLE_ENV_FILE"] = "1"
    return env


def main():
    (ROOT / "build").mkdir(exist_ok=True)
    for name in ("accounts", "complaints", "routing", "workflow", "scms", "scripts",
                 "integration_checks"):
        if not compileall.compile_dir(ROOT / name, quiet=1):
            return 1
    if not compileall.compile_file(ROOT / "manage.py", quiet=1):
        return 1
    env = synthetic_environment(os.environ)
    for command in commands():
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, check=False)  # nosec B603
        except OSError:
            print("CI preflight dependency unavailable (Python/Docker Compose required).", file=sys.stderr)
            return 2
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
