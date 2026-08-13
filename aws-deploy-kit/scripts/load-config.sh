#!/usr/bin/env bash
#
# load-config.sh — resolve and export the deploy configuration.
#
# WHY THIS EXISTS
# Account IDs, hosted zone names, state bucket names, and platform resource
# names are ENVIRONMENT facts, not project facts. Hardcoding them into CLAUDE.md
# or into a committed template does two bad things: it leaks account topology
# into git, and it makes the kit unusable by anyone else without a find-and-
# replace. They live in one gitignored file instead.
#
# Resolution order (first match wins):
#   1. $DEPLOY_CONFIG                 explicit override
#   2. ./.deploy.env                  per-project, gitignored
#   3. ~/.config/aws-deploy-kit/config.env
#   4. ~/.claude/.aws-deploy.env      convenient for Claude Code users
#
# Usage:  . scripts/load-config.sh   (source it; do not execute)
#
set -eu

_candidates="
${DEPLOY_CONFIG:-}
./.deploy.env
${XDG_CONFIG_HOME:-$HOME/.config}/aws-deploy-kit/config.env
$HOME/.claude/.aws-deploy.env
"

DEPLOY_CONFIG_FILE=""
for _c in $_candidates; do
  [ -z "$_c" ] && continue
  if [ -f "$_c" ]; then
    DEPLOY_CONFIG_FILE="$_c"
    break
  fi
done

if [ -z "$DEPLOY_CONFIG_FILE" ]; then
  cat >&2 <<'EOF'
error: no deploy config found.

Create one from the template and fill it in:

  mkdir -p ~/.config/aws-deploy-kit
  cp config.env.example ~/.config/aws-deploy-kit/config.env
  chmod 600 ~/.config/aws-deploy-kit/config.env
  $EDITOR ~/.config/aws-deploy-kit/config.env

It holds the account-specific values (region, state bucket, platform resource
names, hosted zone) that must never be committed.
EOF
  return 1 2>/dev/null || exit 78
fi

# Refuse a world-readable config. It is not supposed to contain credentials,
# but it does describe account topology and people put things in files.
_perms="$(stat -f '%A' "$DEPLOY_CONFIG_FILE" 2>/dev/null || stat -c '%a' "$DEPLOY_CONFIG_FILE" 2>/dev/null || echo '')"
case "$_perms" in
  *[04567][04567]) echo "warning: ${DEPLOY_CONFIG_FILE} is group/world readable; run: chmod 600 ${DEPLOY_CONFIG_FILE}" >&2 ;;
esac

set -a
# shellcheck disable=SC1090
. "$DEPLOY_CONFIG_FILE"
set +a

export DEPLOY_CONFIG_FILE

: "${AWS_REGION:?AWS_REGION missing from $DEPLOY_CONFIG_FILE}"
: "${TF_STATE_BUCKET:?TF_STATE_BUCKET missing from $DEPLOY_CONFIG_FILE}"

echo "==> config: ${DEPLOY_CONFIG_FILE} (region ${AWS_REGION})" >&2
