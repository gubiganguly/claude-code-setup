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
  aws-deploy.env.example     Template for ~/.claude/.aws-deploy.env, the
                             gitignored file holding this account's ID, state
                             bucket, hosted zone, and seed admin credentials.
                             The real one is NEVER in this repo.
  commands/                  All 23 slash commands. /setup scaffolds a project's
                             context/ and docs/ folders plus its CLAUDE.md; the
                             rest are the design workflow (/polish, /critique,
                             /audit, /teach-impeccable, …), /architecture,
                             /readme, and the invoice commands. The global
                             CLAUDE.md references these by name, so a machine
                             without them is broken.
  skills/deploy/             The /deploy procedure. The terraform and templates
                             it drives live in aws-deploy-kit/ (below).
  skills/checkpoint/         Reconciles docs against the code, cleans up dead
                             files, and writes HANDOFF.md for the next agent.
  skills/frontend-design/    Invoked for every new page or screen.
  skills/invoice-parser-gen/ Builds per-vendor invoice parsers.

aws-deploy-kit/              The deployment machinery the /deploy skill drives.
                             bootstrap (state bucket) + platform (VPC, RDS) +
                             four terraform modules + two presets + templates
                             + scripts. Portable: all account-specific values
                             come from the config file, so this directory can
                             be handed to another company as-is.

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

sync.sh                      ./sync.sh snapshot  — refresh this folder from the
                                                   live config after changes
                             ./sync.sh install   — push this folder INTO a new
                                                   machine's live config
```

## The one-paragraph version of how everything works

Code is written locally (Next.js frontend, FastAPI backend, Homebrew Postgres)
and pushed to GitHub over SSH. GitHub Actions builds a Docker image, pushes it
to ECR, runs database migrations as a one-shot task, and only then rolls the
project's Amazon ECS Express Mode (Fargate) service. A failed migration stops
the deploy and leaves the running version serving traffic.

Data lives on a shared RDS Postgres instance (one isolated database per
project) inside a shared VPC. Terraform state is remote, locked, and encrypted.
Each app optionally gets a branded domain via CloudFront; the `/deploy` skill
asks whether you want one rather than assuming.

Cost is roughly $13/mo fixed for the platform database plus about $20/mo per
deployed project. First deploy is one bootstrap script and one `terraform
apply`; every deploy after is `git push`.

## Keeping this snapshot fresh

This folder is a **copy**, not the live config. After meaningful changes to
`~/.claude/CLAUDE.md`, the deploy skill, or the platform terraform, run:

```bash
"./sync.sh" snapshot
```

Snapshot last refreshed: 2026-08-13.
