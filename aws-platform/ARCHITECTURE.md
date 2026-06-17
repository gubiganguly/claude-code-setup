# Deployment Architecture — Plain-English Guide

How code gets from a laptop to a live URL in this setup, and what every service
in the chain actually does. Written for humans; the operational how-to lives in
[README.md](README.md), and the deploy procedure is automated by the `/deploy`
Claude Code skill.

---

## The big picture

Software exists in three places:

1. **Your laptop** — write code, run it locally
2. **GitHub** — the shared source of truth for the code
3. **AWS** — where the live, public version runs

Everything below is the machinery that moves code 1 → 2 → 3 reliably and keeps
the data safe along the way.

```
 laptop ──git push──▶ GitHub ──GitHub Actions builds image──▶ ECR (image shelf)
                                                                │
   Internet ──HTTPS──▶ App Runner (runs the container) ◀──pulls─┘
                            │ private network (VPC), outbound via NAT
                            ▼
                     RDS Postgres "platform-db"
                     (one database per project)

   Secrets Manager ──injected as env vars──▶ App Runner
   Terraform ──creates/updates all of the above
   CloudWatch ◀──application logs
```

---

## The services, one by one

| Service | One-liner |
|---|---|
| **Docker** | Freezes your app + all dependencies into a *container image* — a sealed box that runs identically anywhere. Recipe = the `Dockerfile` in the repo. |
| **GitHub Actions** | GitHub's build robot. On every push to `main`: build the image, push to ECR, trigger an App Runner deploy. This is the CI/CD pipeline. |
| **OIDC** | How GitHub Actions proves its identity to AWS cryptographically — no AWS password stored in GitHub. |
| **ECR** | Elastic Container Registry — a private shelf in AWS that stores container images. One repo per project. |
| **App Runner** | Runs the container: public HTTPS URL, restarts on crash, scales on traffic. "Serverless" = you never see or manage the underlying machine. |
| **RDS** | Relational Database Service — AWS running Postgres *for* you: patching, nightly backups, hardware. One instance (`platform-db`) hosts a separate database per project. |
| **Secrets Manager** | Encrypted vault for passwords/API keys. App Runner fetches them at boot and hands them to the app as env vars — secrets never appear in code or the repo. |
| **IAM** | AWS's permission system. Each app may read only *its own* secrets; each repo's CI role may push only to *its own* ECR repo and deploy only *its own* service. |
| **VPC** | Your private network inside AWS (`platform-vpc`, 10.10.0.0/16). Apps' network interfaces and the database live here, unreachable from outside. |
| **Subnets** | Zones of the VPC. *Public* = reachable from the internet; *private* = not. App traffic sits in private subnets. |
| **NAT gateway** | One-way door for private subnets: apps can call out (e.g. the Anthropic API) but nothing can connect in. The priciest piece (~$32/mo) — shared across all projects. |
| **Security groups** | Per-resource firewalls. The DB's rule: accept Postgres connections only from the apps' security group + the operator's IP. |
| **Route 53** | AWS's DNS service. The zone `apps.snhcap.com` is delegated here from GoDaddy (where snhcap.com lives); each project gets `<project>.apps.snhcap.com` pointing at its App Runner service, with an auto-issued TLS certificate. Branded domains also avoid Microsoft Defender's "might not be safe" warning that raw `*.awsapprunner.com` URLs trigger. |
| **Terraform** | Infrastructure as code. All of the above is described in `.tf` files; `terraform apply` makes AWS match. Reproducible, reviewable, no console clicking. |
| **CloudWatch** | Where the app's logs land. First stop when production misbehaves. |

---

## Shared platform vs. dedicated

The expensive, mostly-idle pieces — VPC, NAT, the RDS instance — are stood up
**once** in this repo and shared by every small project (**shared mode**,
~$45/mo fixed + ~$5/mo per project). Each project still gets fully separate:
ECR repo, App Runner service, secrets, IAM roles, and its **own database +
login** on the shared RDS instance.

Apartment-building analogy: `platform-db` is the building, each project's
database is a locked apartment. Portco A's credentials cannot read Portco B's
data — Postgres enforces it. What IS shared: the machine's CPU/disk (a heavy
neighbor can slow others) and maintenance windows (a restart touches everyone).
Fine for small internal apps; that's the trade for the price.

**Graduation path:** when one app earns real users/load/data-sensitivity,
redeploy it in **dedicated mode** (own VPC + own RDS, ~$50/mo) and move its
database with `pg_dump`/`pg_restore`. Only the connection string changes.

---

## Lifecycle of a project

**Local dev.** Next.js / FastAPI against Homebrew Postgres on the laptop. AWS
is not involved. Local DB is throwaway and totally separate from production.

**First deploy (`/deploy`, once, ~3 min + ~15 min for the certificate).**
Terraform creates the per-project pieces, a database + role on `platform-db`,
and the custom domain `<project>.apps.snhcap.com`. Share the custom domain,
not the raw AWS URL.

**Every deploy after (`git push`).** GitHub Actions builds the image → pushes
to ECR → pokes App Runner. App Runner boots the new container *alongside* the
old one, the container runs DB migrations on boot, the health check
(`/api/health`) must pass, and only then does traffic switch. A broken build
never receives traffic — the old version keeps serving.

**Runtime request path.** User → App Runner URL → container → its own database
on RDS (through the VPC, vetted by security groups) → external API calls exit
via the NAT → logs to CloudWatch.

**Schema changes.** Never edit the production DB by hand. A *migration* is a
small versioned script in the repo ("add column X"); the container applies
pending migrations at boot, so the DB's shape always updates in lockstep with
the code that expects it.

---

## The one mental model to keep

Every deploy throws the old container away and replaces it — nothing "edits the
server." The **only** thing with memory between deploys is the database. That's
why RDS gets backups, deletion protection, and a never-destroy rule, while
everything else is rebuildable in minutes from the repo + Terraform.

> Everything except the database is cattle. The database is the pet.
