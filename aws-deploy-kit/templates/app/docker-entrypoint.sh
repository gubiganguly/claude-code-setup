#!/bin/sh
#
# docker-entrypoint.sh — start the app. That is all it does.
#
# WHAT CHANGED FROM v1
# v1 ran `prisma migrate deploy` and four seed scripts here, on every container
# boot. Three problems with that:
#   * a bad migration crash-looped the service with no way to roll back
#   * demo seed data was re-applied to production on every restart
#   * scaling past one task meant N containers racing the same migration
#
# Migrations now run as a one-shot task in CI, before the rollout. Seeds are
# opt-in via RUN_SEEDS and default to off.
#
set -e

# Seeds are for demo environments. RUN_SEEDS is set by Terraform and defaults
# to "false" everywhere that has real users.
if [ "${RUN_SEEDS:-false}" = "true" ]; then
  echo "[entrypoint] RUN_SEEDS=true, applying seeds"
  for seed in prisma/seed.ts prisma/seed-*.ts; do
    [ -f "$seed" ] || continue
    echo "[entrypoint]   $seed"
    # Seeds are advisory. A failed seed logs and continues; it must never stop
    # a healthy build from serving traffic.
    node node_modules/tsx/dist/cli.mjs "$seed" || \
      echo "[entrypoint]   WARNING: $seed failed, continuing"
  done
fi

# Next's standalone server binds to $HOSTNAME. Container runtimes set that to
# the container ID, which is not a bindable address, so the server comes up
# unreachable and fails ALB health checks. Force it.
export HOSTNAME=0.0.0.0
export PORT="${PORT:-3000}"

echo "[entrypoint] starting on ${HOSTNAME}:${PORT}"
exec node server.js
