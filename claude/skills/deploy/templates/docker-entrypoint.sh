#!/bin/sh
set -e

# 1) Apply pending DB migrations (fast, idempotent, advisory-locked → safe with
#    concurrent instances). Fatal if it fails — a broken schema should stop boot.
echo "[entrypoint] applying database migrations (prisma migrate deploy)…"
node node_modules/prisma/build/index.js migrate deploy

# 2) Seed demo data. Every seed script is idempotent (no-ops once applied), so
#    this is safe to run on every boot. Non-fatal: a seed hiccup logs a warning
#    but still lets the server start.
echo "[entrypoint] seeding demo data (idempotent)…"
if node node_modules/tsx/dist/cli.mjs prisma/seed.ts \
  && node node_modules/tsx/dist/cli.mjs prisma/seed-phase2.ts \
  && node node_modules/tsx/dist/cli.mjs prisma/seed-phase3.ts \
  && node node_modules/tsx/dist/cli.mjs prisma/seed-demo-users.ts; then
  echo "[entrypoint] seed complete"
else
  echo "[entrypoint] WARNING: seed step failed — continuing to start server"
fi

# 3) Start the Next.js standalone server.
# Force-bind to 0.0.0.0. Next's standalone server binds to $HOSTNAME; if the
# container runtime sets HOSTNAME to a non-routable value the server becomes
# unreachable and fails ALB health checks. Override it here to be safe.
export HOSTNAME=0.0.0.0
export PORT="${PORT:-3000}"
echo "[entrypoint] starting Next.js server on ${HOSTNAME}:${PORT}"
exec node server.js
