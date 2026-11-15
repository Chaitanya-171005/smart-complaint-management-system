#!/bin/sh
# Prove persistence using uniquely named disposable PostgreSQL/evidence volumes.
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"
command -v docker >/dev/null 2>&1 || { echo 'Docker CLI is required.' >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo 'Docker daemon is unavailable.' >&2; exit 2; }
command -v openssl >/dev/null 2>&1 || { echo 'openssl is required.' >&2; exit 2; }

project="scms-e03-persist-$(openssl rand -hex 16)"
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] ||
        [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] ||
        [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ] ||
        docker volume inspect "${project}_postgres_data" >/dev/null 2>&1 ||
        docker volume inspect "${project}_private_evidence" >/dev/null 2>&1 ||
        docker network inspect "${project}_default" >/dev/null 2>&1; then
    echo 'Generated Compose project already exists; refusing to touch it.' >&2
    exit 2
fi
tmpdir=$(mktemp -d)
env_file="$tmpdir/compose.env"
chmod 700 "$tmpdir"

cleanup() {
    # The unique project name scopes removal to this run's disposable volumes.
    docker compose -p "$project" --env-file "$env_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

db_password=$(openssl rand -hex 24)
cat >"$env_file" <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_DB_NAME=scms_persist
DJANGO_DB_USER=scms_persist
DJANGO_DB_PASSWORD=$db_password
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
COMPLAINT_INTAKE_ENABLED=False
COMPLAINT_EMERGENCY_NOTICE=
APP_PORT=0
EOF
chmod 600 "$env_file"

compose() { docker compose -p "$project" --env-file "$env_file" "$@"; }
compose up -d --build --wait
compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE TABLE e03_persistence_probe (value text NOT NULL)" -c "INSERT INTO e03_persistence_probe VALUES (\$tag\$database-survived-replacement\$tag\$)"' >/dev/null
compose exec -T app sh -c 'printf %s evidence-survived-replacement > "$PRIVATE_EVIDENCE_ROOT/e03-persistence-probe"'

# Recreate both containers while retaining only this run's isolated volumes.
compose up -d --force-recreate --wait db app
db_value=$(compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT value FROM e03_persistence_probe"')
evidence_value=$(compose exec -T app cat /data/private-evidence/e03-persistence-probe)
[ "$db_value" = database-survived-replacement ] || { echo 'Database data did not survive replacement.' >&2; exit 1; }
[ "$evidence_value" = evidence-survived-replacement ] || { echo 'Evidence data did not survive replacement.' >&2; exit 1; }
echo 'Disposable PostgreSQL and private-evidence volumes survived app and database container replacement.'
