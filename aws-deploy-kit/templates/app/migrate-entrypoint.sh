#!/bin/sh
#
# migrate-entrypoint.sh — apply database migrations, then exit.
#
# Runs as a one-shot Fargate task from CI, using the SAME image as the app, so
# the migrations are always exactly the ones that shipped with this build.
#
# Exit code is the contract: non-zero fails the deploy and leaves the currently
# running version untouched.
#
set -e

echo "[migrate] applying migrations"
node node_modules/prisma/build/index.js migrate deploy
echo "[migrate] complete"
