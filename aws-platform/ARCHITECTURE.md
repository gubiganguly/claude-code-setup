# Deployment Architecture — Plain-English Guide

How code gets from a laptop to a live URL in this setup, and what every service
in the chain actually does. Written for humans; the operational how-to lives in
[README.md](README.md), and the deploy procedure is automated by the `/deploy`
Claude Code skill.

> **Runtime: Amazon ECS Express Mode (Fargate).** This replaced AWS App Runner
> in June 2026, after AWS stopped accepting new App Runner customers. If you
> find a doc that says App Runner, it predates the migration. The only App
> Runner artifact still in the account is an unused VPC connector (see
> [Known leftovers](#known-leftovers)).

---

## The big picture

Software exists in three places:

1. **Your laptop**: write code, run it locally
2. **GitHub**: the shared source of truth for the code
3. **AWS**: where the live, public version runs

Everything below is the machinery that moves code 1 → 2 → 3 reliably and keeps
the data safe along the way.

```
 laptop ──git push──▶ GitHub ──Actions builds image──▶ ECR (image shelf)
                                                            │
                                                     pulls  │
                                                            ▼
 user ──HTTPS──▶ CloudFront ──────▶ ALB ──────▶ ECS Express task (Fargate)
      <project>.apps.snhcap.com   (Express-managed,          │
       (branded, ACM cert)         shared, *.on.aws)         │
                                                             │ public subnet,
                                                             │ egress via IGW
                                                             ▼
                                                RDS Postgres "platform-db"
                                                (one database per project)

 Secrets Manager ──injected as env vars at boot──▶ task
 Terraform ──creates/updates all of the above
 CloudWatch ◀──application logs
```

---

## The services, one by one

| Service | One-liner |
|---|---|
| **Docker** | Freezes your app plus all dependencies into a *container image*, a sealed box that runs identically anywhere. Recipe = the `Dockerfile` in the repo. |
| **GitHub Actions** | GitHub's build robot. On every push to `main`: build the image, push to ECR, roll the ECS Express service. This is the CI/CD pipeline. |
| **OIDC** | How GitHub Actions proves its identity to AWS cryptographically. No AWS password is stored in GitHub. |
| **ECR** | Elastic Container Registry, a private shelf in AWS that stores container images. One repo per project. |
| **ECS Express Mode** | The runtime. One Terraform resource (`aws_ecs_express_gateway_service`) stands up the whole production stack: a Fargate task, a load balancer with an HTTPS listener and certificate, a target group, security groups, auto-scaling, and an AWS-provided `*.on.aws` URL. Everything runs in the shared `default` ECS cluster. |
| **Fargate** | The compute under ECS. AWS runs the container without you managing servers. You pay per vCPU-second and GB-second while a task runs. |
| **ALB** | Application Load Balancer. Express creates and manages these for you and **shares them across services** (currently 5 ALBs carrying every project), so you never see one in the project's Terraform. It terminates HTTPS and routes to the healthy task. |
| **CloudFront** | AWS's CDN, and the piece that gives each app its branded domain. The Express service's own URL is an ugly `*.on.aws` address that Microsoft Defender flags as suspicious, so CloudFront sits in front with `<project>.apps.snhcap.com` and an ACM certificate. Always share the branded URL, never the raw origin. |
| **RDS** | Relational Database Service, AWS running Postgres *for* you: patching, nightly backups, hardware. One instance (`platform-db`, Postgres 17) hosts a separate database per project. |
| **Secrets Manager** | Encrypted vault for passwords and API keys. The task's execution role fetches them at boot and hands them to the app as env vars, so secrets never appear in code or the repo. |
| **IAM** | AWS's permission system. Each app may read only *its own* secrets; each repo's CI role may push only to *its own* ECR repo and deploy only *its own* service. Express also needs an *infrastructure role*, which is what lets it manage load balancers and scaling on your behalf. |
| **VPC** | The private network inside AWS (`platform-vpc`, 10.10.0.0/16). Every shared-mode project and the database live here. |
| **Subnets** | Zones of the VPC. There are two public (10.10.1.0/24, 10.10.2.0/24) and two private (10.10.11.0/24, 10.10.12.0/24). **Express tasks run in the public subnets** so Express can give them an internet-facing load balancer, and they reach the internet through the internet gateway. See [Networking, honestly](#networking-honestly) for why that is safe. |
| **Internet gateway** | The VPC's door to the internet. Public subnets route outbound traffic through it, which is how Express tasks call external APIs. |
| **NAT gateway** | One-way outbound door for the *private* subnets: things there can call out but nothing can connect in. It is the priciest single piece of the platform and Express tasks do not use it. It remains because the private subnets and their route tables still exist. |
| **Security groups** | Per-resource firewalls. `platform-ecs-egress` is attached to every project's tasks and allows all outbound but no inbound (Express manages inbound on its own service security group). `platform-rds-sg` is what protects the database: it accepts Postgres only from `platform-ecs-egress` and from the operator IPs in `admin_cidrs`. |
| **Route 53** | AWS's DNS service. The zone `apps.snhcap.com` is delegated here from GoDaddy (where snhcap.com lives) via NS records; each project gets `<project>.apps.snhcap.com` pointing at its CloudFront distribution. |
| **ACM** | Certificate Manager, which issues and auto-renews the TLS certificates for the branded domains. Validation is DNS-based through Route 53, which is why the zone delegation has to be correct. |
| **Terraform** | Infrastructure as code. All of the above is described in `.tf` files; `terraform apply` makes AWS match. Reproducible, reviewable, no console clicking. |
| **CloudWatch** | Where the app's logs land. First stop when production misbehaves. |

---

## Networking, honestly

The older version of this document claimed apps and the database sat in private
subnets, unreachable from outside. That is not how the platform is actually
built, and the real design is worth understanding because it looks alarming
until you see the reasoning.

**Express tasks run in the public subnets.** Express only gives you an
internet-facing load balancer if the tasks live in subnets that route to an
internet gateway. Public subnet does not mean unprotected: inbound traffic is
still governed by the security group Express manages, which only accepts
traffic from its load balancer.

**`platform-db` has `publicly_accessible = true`.** It sits in the public
subnets too. The reason is practical: `/deploy` provisions each project's
database and role, and runs migrations, from the operator's laptop, and a
publicly resolvable endpoint avoids running a bastion host for that. The
protection is entirely the security group. `platform-rds-sg` opens 5432 to
exactly two things: the `platform-ecs-egress` security group (so tasks can
connect) and the specific operator IPs listed in `admin_cidrs`. Everything else
is refused at the network layer before Postgres ever sees it.

Be aware that this is a deliberate trade, and that it is stricter in practice
than "publicly accessible" sounds but weaker than the private-subnet design it
replaced. Two consequences worth remembering:

- **Your IP matters.** When your home or office IP changes, `/deploy` and
  `psql` stop working until `admin_cidrs` is updated and re-applied.
- **The security group is the only thing standing between the internet and the
  database.** Never widen `admin_cidrs` to `0.0.0.0/0`, not even briefly.

If a project ever holds data where this trade is unacceptable, that is the
signal to graduate it to dedicated mode with a genuinely private database.

---

## Shared platform vs. dedicated

The expensive, mostly-idle pieces (VPC, NAT, the RDS instance) are stood up
**once** in this repo and shared by every small project (**shared mode**). Each
project still gets fully separate: ECR repo, ECS Express service, secrets, IAM
roles, CloudFront distribution, branded domain, and its **own database and
login** on the shared RDS instance.

Apartment-building analogy: `platform-db` is the building, each project's
database is a locked apartment. Portco A's credentials cannot read Portco B's
data, and Postgres enforces it. What IS shared: the instance's CPU and disk (a
heavy neighbor can slow others) and maintenance windows (a restart touches
everyone). Fine for small internal apps, and that is the trade for the price.

**Graduation path:** when one app earns real users, real load, or sensitive
data, redeploy it in **dedicated mode** (own VPC and own RDS) and move its
database with `pg_dump` and `pg_restore`. Only the connection string changes.

See [README.md](README.md) for what this actually costs, which is more than the
older estimates in these docs used to claim.

---

## Lifecycle of a project

**Local dev.** Next.js and FastAPI against Homebrew Postgres on the laptop. AWS
is not involved. The local database is throwaway and completely separate from
production.

**First deploy (`/deploy`, once, a few minutes plus certificate validation).**
Terraform creates the per-project pieces, a database and role on `platform-db`,
the CloudFront distribution, and the custom domain
`<project>.apps.snhcap.com`. Share the custom domain, never the raw `*.on.aws`
origin.

**Every deploy after (`git push`).** GitHub Actions builds the image, pushes it
to ECR, and rolls the Express service. Express starts the new task *alongside*
the old one, the container runs database migrations on boot, the health check
(`/api/health`) must pass, and only then does traffic switch. A broken build
never receives traffic, because the old version keeps serving.

**Runtime request path.** User → branded domain → CloudFront → Express-managed
ALB → the container → its own database on RDS (vetted by security groups) →
external API calls exit through the internet gateway → logs to CloudWatch.

**Schema changes.** Never edit the production database by hand. A *migration*
is a small versioned script in the repo ("add column X"); the container applies
pending migrations at boot, so the database's shape always updates in lockstep
with the code that expects it.

---

## Known leftovers

Honest notes about things in the account that the architecture no longer needs.
Neither is load-bearing; both are safe to remove when someone has time, and
neither should be built on.

- **`platform-shared` App Runner VPC connector.** Still declared in
  `terraform/rds.tf` and still ACTIVE in AWS, left over from the App Runner
  era. No App Runner services exist anymore, so nothing uses it.
- **The private subnets and NAT gateway.** Express tasks egress through the
  internet gateway instead, so the NAT is no longer on the request path for
  new deploys. It still carries real monthly cost, so it is worth confirming
  what (if anything) still routes through it before assuming it can go.

---

## The one mental model to keep

Every deploy throws the old container away and replaces it. Nothing "edits the
server." The **only** thing with memory between deploys is the database. That
is why RDS gets backups, deletion protection, and a never-destroy rule, while
everything else is rebuildable in minutes from the repo plus Terraform.

> Everything except the database is cattle. The database is the pet.
