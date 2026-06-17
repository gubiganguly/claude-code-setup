# New Machine Setup — SNH Claude Code Environment

Everything needed to replicate the SNH development + deployment setup on a
fresh Mac. Follow top to bottom; each step ends with a verification command.

---

## 1. Install the tools (Homebrew)

```bash
# Homebrew itself (if missing)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Core toolchain
brew install awscli terraform gh node python postgresql@17
brew install --cask docker        # Docker Desktop — open it once so the daemon runs
```

Verify:

```bash
aws --version && terraform -version && gh --version && node -v && python3 -V
docker info | head -3             # daemon must be running
/usr/local/opt/postgresql@17/bin/psql --version   # (Apple Silicon: /opt/homebrew/opt/...)
```

## 2. Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
claude --version
claude          # first run walks through Anthropic login
```

## 3. AWS CLI authentication

You need an IAM user in the SNH AWS account (346698404534) with access keys
(an admin creates one in IAM → Users → Security credentials → Create access key).

```bash
aws configure
# AWS Access Key ID:     <from IAM>
# AWS Secret Access Key: <from IAM>
# Default region name:   us-east-1
# Default output format: json
```

Verify (must show account 346698404534):

```bash
aws sts get-caller-identity
```

## 4. GitHub — CLI + SSH

We ALWAYS use SSH for git remotes (HTTPS OAuth tokens break on workflow-file
pushes).

```bash
# 4a. SSH key
ssh-keygen -t ed25519 -C "you@snhcap.com"          # accept defaults
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# 4b. GitHub CLI login (choose SSH as the git protocol when prompted,
#     and let it upload your new public key)
gh auth login

# 4c. Verify
ssh -T git@github.com          # "Hi <user>! You've successfully authenticated"
gh auth status
```

If a repo was cloned over HTTPS, switch it:
`git remote set-url origin git@github.com:owner/repo.git`

## 5. Install the Claude Code configuration

From this folder:

```bash
./sync.sh install
```

(Or manually: copy `claude/CLAUDE.md` → `~/.claude/CLAUDE.md`,
`claude/commands/` → `~/.claude/commands/`, `claude/skills/deploy/` →
`~/.claude/skills/deploy/`, and make sure `create-db.sh` stays executable.)

This gives every Claude Code session the SNH conventions (stack, folder
structure, auth/RBAC baseline, UI standards) plus the `/setup` command and
the `/deploy` skill.

## 6. The shared deployment platform

The platform (shared VPC + NAT + RDS Postgres + App Runner connector) should
already exist in the AWS account — check:

```bash
aws ec2 describe-vpcs --filters Name=tag:Name,Values=platform-vpc --query "Vpcs[0].VpcId"
```

- **It exists (normal case):** nothing to do. Get your public IP
  (`curl checkip.amazonaws.com`) and ask whoever operates
  `~/Development/aws-platform` to add it to `admin_cidrs` — needed for /deploy
  to provision databases from your machine.
- **It doesn't exist (brand-new AWS account):** copy `aws-platform/` from this
  folder to `~/Development/aws-platform`, create
  `terraform/terraform.tfvars` with your IP in `admin_cidrs`, then
  `terraform init && terraform apply` (≈15 min; creates ~$45/mo of infra).
  Read `aws-platform/README.md` first. Then wire up DNS: the apply creates a
  Route 53 zone for `apps.snhcap.com` and outputs its name servers
  (`terraform output apps_zone_name_servers`) — add those four values as NS
  records named `apps` in GoDaddy's DNS for snhcap.com. Without this, custom
  domains won't validate and apps only get raw `*.awsapprunner.com` URLs
  (which Microsoft Defender flags as suspicious).

## 7. Smoke test

```bash
mkdir /tmp/cc-test && cd /tmp/cc-test && claude
# In the session:  /setup        → should create .claude/ with project files
# Conventions check: ask "what stack do we use?" → should answer from CLAUDE.md
```

---

## What's where (after setup)

| Thing | Location |
|---|---|
| Global conventions | `~/.claude/CLAUDE.md` |
| `/setup` command | `~/.claude/commands/setup.md` |
| `/deploy` skill + templates | `~/.claude/skills/deploy/` |
| Shared platform Terraform | `~/Development/aws-platform/terraform/` |
| Architecture explainer | `~/Development/aws-platform/ARCHITECTURE.md` |
