#!/usr/bin/env bash
###############################################################################
# sync.sh — keep this snapshot folder and the live Claude Code setup in sync.
#
#   ./sync.sh snapshot   copy LIVE config -> this folder (refresh the backup)
#   ./sync.sh install    copy this folder -> LIVE config (new machine setup)
#
# Live locations: ~/.claude/{CLAUDE.md,commands,skills} and
# ~/Development/aws-platform. Terraform state/tfvars are never copied.
#
# Deliberately NOT synced:
#   ~/.claude/settings.json   can hold plaintext MCP tokens; per-machine only
#   ~/.claude/plugins/        org-managed + marketplace, not file-copyable
###############################################################################
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  snapshot)
    cp ~/.claude/CLAUDE.md claude/CLAUDE.md

    # ALL slash commands, not just setup.md — the global CLAUDE.md references
    # /polish, /critique, /audit, /teach-impeccable and friends by name.
    rm -rf claude/commands
    mkdir -p claude/commands
    cp ~/.claude/commands/*.md claude/commands/

    # ALL skills (deploy, frontend-design, invoice-parser-gen, ...)
    rm -rf claude/skills
    mkdir -p claude/skills
    cp -R ~/.claude/skills/. claude/skills/
    # Drop Python build artifacts that ride along with the invoice skill.
    find claude/skills -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find claude/skills -name '*.pyc' -delete 2>/dev/null || true

    cp ~/Development/aws-platform/README.md ~/Development/aws-platform/ARCHITECTURE.md aws-platform/
    cp ~/Development/aws-platform/terraform/*.tf aws-platform/terraform/

    # The deploy kit. The /deploy skill is only a procedure; the terraform,
    # templates, and scripts it drives live here. Without it a fresh install
    # gets a skill that references a directory that does not exist.
    # Its own .git and any real config are excluded.
    if [ -d ~/Development/aws-deploy-kit ]; then
      rm -rf aws-deploy-kit
      mkdir -p aws-deploy-kit
      rsync -a \
        --exclude '.git/' \
        --exclude '.terraform/' \
        --exclude '*.tfstate*' \
        --exclude 'terraform.tfvars' \
        --exclude 'config.env' \
        --exclude '.deploy.env' \
        --exclude '.DS_Store' \
        ~/Development/aws-deploy-kit/ aws-deploy-kit/
    fi

    echo "Snapshot refreshed from live config ($(date '+%Y-%m-%d %H:%M'))."
    echo "  commands:   $(ls -1 claude/commands/*.md | wc -l | tr -d ' ') files"
    echo "  skills:     $(ls -1d claude/skills/*/ | wc -l | tr -d ' ') dirs"
    echo "  deploy kit: $(find aws-deploy-kit -type f 2>/dev/null | wc -l | tr -d ' ') files"
    ;;
  install)
    mkdir -p ~/.claude/commands ~/.claude/skills
    cp claude/CLAUDE.md ~/.claude/CLAUDE.md
    cp claude/commands/*.md ~/.claude/commands/

    # Replace only the skills this snapshot ships; leave any others in place.
    for d in claude/skills/*/; do
      n=$(basename "$d")
      rm -rf ~/.claude/skills/"$n"
      cp -R "$d" ~/.claude/skills/"$n"
    done
    # Restore the executable bit that git does not preserve on copy. Guarded,
    # because which scripts exist changes between skill versions and this
    # script runs under `set -e`.
    find ~/.claude/skills -name '*.sh' -exec chmod +x {} + 2>/dev/null || true

    if [ ! -d ~/Development/aws-platform ]; then
      mkdir -p ~/Development
      cp -R aws-platform ~/Development/aws-platform
      echo "NOTE: ~/Development/aws-platform created from snapshot. If the"
      echo "platform already runs in AWS, you also need its terraform.tfstate"
      echo "from the original machine before running terraform there."
    fi

    if [ -d aws-deploy-kit ] && [ ! -d ~/Development/aws-deploy-kit ]; then
      mkdir -p ~/Development
      cp -R aws-deploy-kit ~/Development/aws-deploy-kit
      find ~/Development/aws-deploy-kit -name '*.sh' -exec chmod +x {} + 2>/dev/null || true
      echo "Deploy kit installed to ~/Development/aws-deploy-kit"
    fi

    if [ ! -f ~/.claude/.aws-deploy.env ]; then
      echo ""
      echo "ACTION REQUIRED: ~/.claude/.aws-deploy.env does not exist."
      echo "  The /deploy skill reads account settings from it and will not"
      echo "  run without one. Create it from claude/aws-deploy.env.example:"
      echo "    cp claude/aws-deploy.env.example ~/.claude/.aws-deploy.env"
      echo "    chmod 600 ~/.claude/.aws-deploy.env"
      echo "  Then fill in the values. It is deliberately NOT in this repo:"
      echo "  it holds the AWS account ID and the seed admin password."
    fi

    echo "Live config installed. See docs/NEW-MACHINE-SETUP.md for the rest."
    echo "Reminder: plugins and MCP servers are NOT installed by this script."
    ;;
  *)
    echo "usage: $0 snapshot|install" >&2
    exit 1
    ;;
esac
