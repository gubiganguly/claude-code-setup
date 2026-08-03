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
`claude/commands/` → `~/.claude/commands/`, `claude/skills/` →
`~/.claude/skills/`, and make sure `create-db.sh` stays executable.)

This gives every Claude Code session the SNH conventions (stack, folder
structure, auth/RBAC baseline, security standards, UI and design standards,
the design workflow, the `/context` folder convention, data reporting
standards, and writing rules) plus all the slash commands and skills.

Verify the commands and skills landed:

```bash
ls ~/.claude/commands/ | wc -l     # expect ~23 .md files, not 1
ls ~/.claude/skills/               # expect deploy, frontend-design, invoice-parser-gen
```

If `commands/` has only `setup.md`, you are running an old snapshot that
predates 2026-08-03. The global CLAUDE.md references `/polish`, `/critique`,
`/audit`, `/teach-impeccable` and others, and they will silently not exist.

## 5b. Plugins (not installed by sync.sh)

Some skills come from plugins rather than this repo, and `sync.sh` cannot
install them:

- **Org-managed plugins** (`snh-ledger`, `cme-corp-brand`,
  `snh-ppt-formatter`, `anthropic-skills`, `cowork-plugin-management`) arrive
  automatically once you log in to Claude Code with your SNH account. Nothing
  to install by hand.
- **Marketplace plugins** come from `anthropics/claude-plugins-official`,
  registered under `~/.claude/plugins/`. Manage them from an interactive
  `claude` session with `/plugin`.

Verify the SNH brand kit is available, since the design workflow depends on it
for SNH-branded projects:

```bash
claude
# In the session, ask: "list the snh-ledger skills you have"
# Expect: ledger-brand, ledger-deck, ledger-pdf, ledger-doc, ledger-chart, ledger-diagram
```

If they are missing, check that you are logged in with the SNH account
(`/status` in an interactive session) before doing anything else. A project
kicked off without them will invent its own brand instead of using The Ledger.

> **Do not copy `~/.claude/settings.json` between machines.** It can contain
> plaintext MCP server tokens. It is deliberately excluded from this snapshot.
> Set up MCP servers fresh on each machine.

## 6. The shared deployment platform

The platform (shared VPC, public + private subnets, NAT, RDS Postgres
`platform-db`, and the shared `platform-ecs-egress` security group that ECS
Express tasks wear) should already exist in the AWS account. Check:

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
  domains won't validate and apps only get the raw `*.on.aws` ECS Express URL
  (which Microsoft Defender flags as suspicious).

  Read the cost table in `aws-platform/README.md` before standing up a new
  account. The real figure is roughly $500/month at a dozen services, not the
  ~$45 the older docs claimed.

## 7. Smoke test

```bash
mkdir /tmp/cc-test && cd /tmp/cc-test && claude
# In the session:  /setup        → should create .claude/ AND a /context folder
#                                  (context/README.md + inbox/ + knowledge/)
# Conventions check: ask "what stack do we use?" → should answer from CLAUDE.md
# Commands check:    type /pol   → /polish should autocomplete
```

---

## What's where (after setup)

| Thing | Location |
|---|---|
| Global conventions | `~/.claude/CLAUDE.md` |
| Slash commands (`/setup`, `/polish`, `/critique`, …) | `~/.claude/commands/` |
| Skills (`deploy`, `frontend-design`, `invoice-parser-gen`) | `~/.claude/skills/` |
| Plugins (org-managed + marketplace) | `~/.claude/plugins/` |
| Shared platform Terraform | `~/Development/aws-platform/terraform/` |
| Architecture explainer | `~/Development/aws-platform/ARCHITECTURE.md` |
| Platform costs + state warning | `~/Development/aws-platform/README.md` |

## Known gaps this doc cannot close

- **Terraform state.** The platform's `terraform.tfstate` lives only on the
  original operator's Mac and is not in version control. A new machine cannot
  manage the existing platform stack without a copy of it. Get it from the
  original machine before running `terraform apply` in
  `~/Development/aws-platform`.
- **MCP servers.** Configured per-machine in `~/.claude/settings.json`, which
  is not snapshotted because it can hold plaintext tokens.
