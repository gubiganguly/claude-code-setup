#!/usr/bin/env bash
###############################################################################
# create-db.sh — Idempotently provision a project database + role on the
# shared platform RDS. Called by terraform (null_resource in db.tf); all
# inputs arrive via environment variables:
#   PLATFORM_HOST, PLATFORM_PORT, MASTER_SECRET_ARN,
#   PROJECT_DB, PROJECT_USER, PROJECT_PASSWORD, AWS_REGION
#
# Safe to re-run: creates the role/database only if missing, always syncs the
# role password to the terraform-managed one.
###############################################################################
set -euo pipefail

# Homebrew keg-only postgres installs aren't on PATH by default.
if ! command -v psql >/dev/null 2>&1; then
  for p in /usr/local/opt/postgresql@{17,16,15}/bin /opt/homebrew/opt/postgresql@{17,16,15}/bin; do
    [ -x "$p/psql" ] && PATH="$p:$PATH" && break
  done
fi
command -v psql >/dev/null 2>&1 || { echo "psql not found — brew install postgresql@17" >&2; exit 1; }

creds=$(aws secretsmanager get-secret-value \
  --secret-id "$MASTER_SECRET_ARN" --region "$AWS_REGION" \
  --query SecretString --output text)
master_user=$(printf '%s' "$creds" | python3 -c 'import sys,json; print(json.load(sys.stdin)["username"])')
master_pass=$(printf '%s' "$creds" | python3 -c 'import sys,json; print(json.load(sys.stdin)["password"])')

run_sql() {
  PGPASSWORD="$master_pass" psql \
    -h "$PLATFORM_HOST" -p "$PLATFORM_PORT" -U "$master_user" -d postgres \
    -v ON_ERROR_STOP=1 --no-psqlrc -tA -c "$1"
}

# Role: create if missing, always sync password (PROJECT_PASSWORD is
# alphanumeric-only by construction, so single-quoting is safe).
run_sql "DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${PROJECT_USER}') THEN
    CREATE ROLE \"${PROJECT_USER}\" LOGIN;
  END IF;
END \$\$;"
run_sql "ALTER ROLE \"${PROJECT_USER}\" WITH LOGIN PASSWORD '${PROJECT_PASSWORD}';"

# Database: create if missing, owned by the project role. On RDS the master
# user must be a member of a role before it can create a database owned by it.
if [ "$(run_sql "SELECT 1 FROM pg_database WHERE datname = '${PROJECT_DB}'")" != "1" ]; then
  run_sql "GRANT \"${PROJECT_USER}\" TO \"${master_user}\";"
  run_sql "CREATE DATABASE \"${PROJECT_DB}\" OWNER \"${PROJECT_USER}\";"
  echo "created database ${PROJECT_DB} owned by ${PROJECT_USER}"
else
  echo "database ${PROJECT_DB} already exists — password synced"
fi
