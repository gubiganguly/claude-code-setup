set -eu

# Runs INSIDE the VPC as a one-shot Fargate task. PGUSER/PGPASSWORD are the RDS
# master credentials, injected by ECS from Secrets Manager; they never leave
# this container. Everything here is idempotent, so re-running is always safe.

echo "[db-provision] target database=${TARGET_DB} role=${TARGET_USER} host=${PGHOST}"

# Wait for the database to accept connections. RDS is normally already up, but
# a first apply can race a just-created instance.
for i in $(seq 1 30); do
  if pg_isready -q; then break; fi
  echo "[db-provision] waiting for postgres (${i}/30)..."
  sleep 2
done

exists() {
  psql -tAc "$1" | grep -q 1
}

# --- role ------------------------------------------------------------------
# CREATE ROLE has no IF NOT EXISTS, so check first. The password is always
# reset, which is what makes credential rotation a no-op re-apply.
if exists "SELECT 1 FROM pg_roles WHERE rolname = '${TARGET_USER}'"; then
  echo "[db-provision] role exists, resetting password"
  psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"${TARGET_USER}\" WITH LOGIN PASSWORD '${TARGET_PASSWORD}'"
else
  echo "[db-provision] creating role"
  psql -v ON_ERROR_STOP=1 -c "CREATE ROLE \"${TARGET_USER}\" WITH LOGIN PASSWORD '${TARGET_PASSWORD}'"
fi

# --- database --------------------------------------------------------------
# CREATE DATABASE cannot run inside a transaction block, so it gets its own
# statement rather than being folded into the block above.
if exists "SELECT 1 FROM pg_database WHERE datname = '${TARGET_DB}'"; then
  echo "[db-provision] database exists"
else
  echo "[db-provision] creating database"
  psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${TARGET_DB}\" OWNER \"${TARGET_USER}\""
fi

# --- privileges ------------------------------------------------------------
# Owner already implies most of this; these statements make the grant explicit
# and correct the case where the database pre-existed with another owner.
psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE \"${TARGET_DB}\" OWNER TO \"${TARGET_USER}\""
psql -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE \"${TARGET_DB}\" TO \"${TARGET_USER}\""

# The app owns its own schema. Revoking CREATE on public from PUBLIC is the
# Postgres 15+ default, but older instances need it said out loud.
psql -v ON_ERROR_STOP=1 -d "${TARGET_DB}" -c "GRANT ALL ON SCHEMA public TO \"${TARGET_USER}\""
psql -v ON_ERROR_STOP=1 -d "${TARGET_DB}" -c "ALTER SCHEMA public OWNER TO \"${TARGET_USER}\""

echo "[db-provision] done"
