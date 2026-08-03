# SNH Claude Code Setup

A complete, portable snapshot of the SNH software development + deployment
environment. Use it to set up a new machine, onboard a teammate, or recover
the setup if anything is lost.

**New machine?** Start with [docs/NEW-MACHINE-SETUP.md](docs/NEW-MACHINE-SETUP.md).
**Want to understand the architecture?** Read [aws-platform/ARCHITECTURE.md](aws-platform/ARCHITECTURE.md).

> **⚠️ Adopting this setup for a different org?** It is hardwired to SNH's
> domain and accounts. Before using it, replace `snhcap.com` with your own
> domain everywhere it appears — `claude/CLAUDE.md` (Domains rule + seed admin
> email `admin@snhcap.com`), `aws-platform/terraform/route53.tf` (the
> `apps.snhcap.com` zone), and the deploy skill's `domain.tf` templates
> (`templates/terraform/` and `templates/terraform-shared/`). You'll also need
> to delegate `apps.<yourdomain>` from YOUR DNS provider to the Route 53 zone
> (see docs/NEW-MACHINE-SETUP.md), and swap the AWS account ID (346698404534)
> and GitHub owner defaults for your own. A quick way to find every spot:
> `grep -ri "snhcap\|346698404534" .`

## What's in here

```
claude/
  CLAUDE.md                  Global conventions every Claude Code session loads:
                             stack (Next.js + FastAPI + Postgres), folder
                             structure, GitHub/SSH rules, auth/RBAC baseline
                             (JWT, admin@snhcap.com seed admin), security
                             standards, UI + design standards, the design
                             workflow (per-project depth tier + SNH-brand
                             kickoff questions, mockup approval), the /context
                             folder convention, data reporting & analytics
                             standards, and writing/copywriting rules.
  commands/                  All 23 slash commands. /setup scaffolds a project's
                             .claude folder + its /context folder; the rest are
                             the design workflow (/polish, /critique, /audit,
                             /teach-impeccable, /animate, …) and the invoice
                             commands. The global CLAUDE.md references these by
                             name, so a machine without them is broken.
  skills/deploy/             The /deploy skill + all its battle-tested templates
                             (Dockerfile, GitHub Actions workflow, Terraform for
                             both SHARED and DEDICATED modes).
  skills/frontend-design/    Invoked for every new page or screen.
  skills/invoice-parser-gen/ Builds per-vendor invoice parsers.

  NOT here: ~/.claude/settings.json (can hold plaintext MCP tokens) and
  ~/.claude/plugins/ (org-managed + marketplace, arrive on SNH login).

aws-platform/
  ARCHITECTURE.md            Plain-English end-to-end explanation of the whole
                             deployment architecture and every AWS service used.
  README.md                  Operating the shared platform (costs, IP changes,
                             graduation path, never-destroy warning).
  terraform/                 Source for the shared platform stack (VPC, NAT,
                             RDS platform-db, shared ALB, platform-ecs-egress SG).
                             NOTE: no tfstate/tfvars here — the LIVE stack and
                             its state live in ~/Development/aws-platform.

docs/
  NEW-MACHINE-SETUP.md       Step-by-step: Homebrew tools, AWS CLI auth,
                             GitHub CLI + SSH keys, Claude Code install,
                             platform check, smoke test.
  AWS-AppRunner-Deployment-Playbook.md
                             The original deep-dive playbook (dedicated mode).

sync.sh                      ./sync.sh snapshot  — refresh this folder from the
                                                   live config after changes
                             ./sync.sh install   — push this folder INTO a new
                                                   machine's live config
```

## The one-paragraph version of how everything works

Code is written locally (Next.js frontend, FastAPI backend, Homebrew Postgres),
pushed to GitHub over SSH, where GitHub Actions builds a Docker image, pushes
it to ECR, and rolls the project's Amazon ECS Express Mode (Fargate) service —
migrations run on boot, health checks gate the traffic switch, so a broken
build never goes live.
Data lives on a shared RDS Postgres instance (`platform-db`, one isolated
database per project) inside a shared VPC — fixed ~$45/mo for the platform,
~$5/mo per deployed project. Each app gets a branded domain
(`<project>.apps.snhcap.com`, Route 53 zone delegated from GoDaddy) with an
auto-issued certificate. First deploy of a project is one `terraform apply`
(the `/deploy` skill does it); every deploy after is `git push`.

## Keeping this snapshot fresh

This folder is a **copy**, not the live config. After meaningful changes to
`~/.claude/CLAUDE.md`, the deploy skill, or the platform terraform, run:

```bash
"./sync.sh" snapshot
```

Snapshot last refreshed: 2026-08-03.
