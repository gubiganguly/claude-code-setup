#!/usr/bin/env bash
###############################################################################
# sync.sh — keep this snapshot folder and the live Claude Code setup in sync.
#
#   ./sync.sh snapshot   copy LIVE config -> this folder (refresh the backup)
#   ./sync.sh install    copy this folder -> LIVE config (new machine setup)
#
# Live locations: ~/.claude/{CLAUDE.md,commands,skills/deploy} and
# ~/Development/aws-platform. Terraform state/tfvars are never copied.
###############################################################################
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  snapshot)
    cp ~/.claude/CLAUDE.md claude/CLAUDE.md
    cp ~/.claude/commands/setup.md claude/commands/setup.md
    rm -rf claude/skills/deploy
    mkdir -p claude/skills
    cp -R ~/.claude/skills/deploy claude/skills/deploy
    cp ~/Development/aws-platform/README.md ~/Development/aws-platform/ARCHITECTURE.md aws-platform/
    cp ~/Development/aws-platform/terraform/*.tf aws-platform/terraform/
    echo "Snapshot refreshed from live config ($(date '+%Y-%m-%d %H:%M'))."
    ;;
  install)
    mkdir -p ~/.claude/commands ~/.claude/skills
    cp claude/CLAUDE.md ~/.claude/CLAUDE.md
    cp claude/commands/setup.md ~/.claude/commands/setup.md
    rm -rf ~/.claude/skills/deploy
    cp -R claude/skills/deploy ~/.claude/skills/deploy
    chmod +x ~/.claude/skills/deploy/templates/terraform-shared/create-db.sh
    if [ ! -d ~/Development/aws-platform ]; then
      mkdir -p ~/Development
      cp -R aws-platform ~/Development/aws-platform
      echo "NOTE: ~/Development/aws-platform created from snapshot. If the"
      echo "platform already runs in AWS, you also need its terraform.tfstate"
      echo "from the original machine before running terraform there."
    fi
    echo "Live config installed. See docs/NEW-MACHINE-SETUP.md for the rest."
    ;;
  *)
    echo "usage: $0 snapshot|install" >&2
    exit 1
    ;;
esac
