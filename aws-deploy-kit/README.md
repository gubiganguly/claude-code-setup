# AWS Deploy Kit

Deploy a containerized web app to AWS with two commands, then `git push` for
every deploy after that.

Built for small teams running several apps in one AWS account. It gives each
app a Fargate service, a database, secrets, a CI pipeline, and optionally a
branded HTTPS domain, while sharing the expensive pieces so a project costs
about **$20/month** instead of about $50.

Works standalone with Terraform and the AWS CLI. Install it as a Claude Code
plugin and `/deploy` walks the whole thing.

---

## What you get

```
your-app.example.com
        │
   CloudFront ── ACM cert, your domain
        │
  ECS Express ALB ── shared across services
        │
   Fargate task ── your container
        │
   RDS Postgres ── private, one database per project
```

Plus: ECR with a rollback window, Secrets Manager, CloudWatch logs, autoscaling,
and a GitHub Actions role using OIDC so no AWS keys exist anywhere.

## Requirements

- Terraform **1.11+** (the S3 backend uses native locking)
- AWS CLI v2, authenticated
- Docker (running)
- GitHub CLI, for wiring up CI

---

## Setup: three stacks, in order

### 1. Bootstrap, once per AWS account

Creates the encrypted, versioned S3 bucket that holds all Terraform state, and
the GitHub OIDC provider.

```bash
cd terraform/bootstrap
terraform init
terraform apply -var org_slug=acme
terraform output -raw backend_config
```

If the account already has a GitHub OIDC provider, add
`-var create_github_oidc_provider=false`.

### 2. Platform, once per AWS account

The shared VPC, the Postgres instance every project gets a database on, the
ECS cluster, and optionally a Route 53 zone for branded domains.

```bash
cd terraform/platform
# paste the backend_config from step 1 into main.tf, key = platform/terraform.tfstate
terraform init
terraform apply -var hosted_zone_name=apps.example.com
terraform output hosted_zone_name_servers   # delegate these at your registrar
terraform output deploy_config              # goes into your config file next
```

Leave `hosted_zone_name` empty if you do not want custom domains.

> **Delegate the zone before deploying anything with a domain.** ACM validation
> waits on DNS forever, with no error, until the registrar points at these name
> servers.

### 3. Config file, once per machine

The one file holding account-specific values. Never committed.

```bash
mkdir -p ~/.config/aws-deploy-kit
cp config.env.example ~/.config/aws-deploy-kit/config.env
chmod 600 ~/.config/aws-deploy-kit/config.env
```

Fill it from the two `terraform output` commands above. This is what keeps
account IDs, bucket names, and internal domains out of every other file in
every repo, including `CLAUDE.md`.

---

## Deploying an app

```bash
# in your app repo
cp -r <kit>/terraform/presets/nextjs-prisma infra/terraform
cp <kit>/templates/app/Dockerfile .
cp <kit>/templates/app/docker-entrypoint.sh .
cp <kit>/templates/app/migrate-entrypoint.sh .
cp <kit>/templates/ci/deploy.yml .github/workflows/

cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars        # service_name, github_*, domain, sizing
$EDITOR main.tf                 # backend block from bootstrap output

<kit>/scripts/bootstrap-image.sh my-app
terraform init && terraform apply
```

Then set any API keys and wire up CI:

```bash
aws secretsmanager put-secret-value --secret-id my-app/anthropic-api-key --secret-string 'sk-...'
terraform output -raw gh_variable_commands   # run what it prints
terraform output -raw app_url
```

Every deploy after this is `git push`.

### Domains are optional

In `terraform.tfvars`:

```hcl
custom_domain    = "my-app.apps.example.com"
hosted_zone_name = "apps.example.com"
```

Leave `custom_domain = ""` and the app is served at its AWS `*.on.aws` URL with
no CloudFront or ACM. That is fine for a short internal spike. For anything you
will send to another person, use a domain: raw `*.on.aws` URLs have no domain
reputation and some corporate mail filters flag them as suspicious.

The domain does not have to be under your default zone. Any Route 53 public
hosted zone you control works, including a customer's.

---

## Layout

```
terraform/
  bootstrap/        state bucket + OIDC provider      (once per account)
  platform/         VPC, RDS, cluster, DNS zone       (once per account)
  modules/
    app-service/    the generic core: any container, any port
    database/       a database + role, provisioned inside the VPC
    domain/         ACM + CloudFront + Route 53
    github-oidc/    least-privilege CI deploy role
  presets/
    nextjs-prisma/  Next.js + Prisma + Postgres
    generic/        any container with a health endpoint
templates/
  app/              Dockerfile, entrypoints
  ci/               GitHub Actions workflow
scripts/
  bootstrap-image.sh  seeds ECR so the first apply is a single command
  psql.sh             psql against the private database, from inside the VPC
  load-config.sh      resolves the config file
skills/deploy/      the Claude Code skill
```

`modules/app-service` knows nothing about Node, Next.js, Prisma, or Postgres.
Anything framework-specific lives in a preset. To support a new stack, copy
`presets/generic` and set the port, health path, and env.

---

## Design decisions worth knowing

**State is remote and locked.** Local state cannot be shared, cannot be locked
against concurrent applies, and stores resource attributes in plaintext on one
machine. The bootstrap stack is the sole exception, because it has nowhere to
put remote state until it has run.

**The database is private.** Databases are created by a one-shot Fargate task
inside the VPC, not by psql from a laptop. That means no public RDS endpoint,
no IP allowlist to maintain, and a first deploy that works identically from CI.
For ad-hoc queries, `scripts/psql.sh` runs psql the same way.

**Secrets never enter Terraform.** Terraform creates the secret container and
ignores its value. Real values are written with `put-secret-value`. Anything
passed as a Terraform variable ends up in state in cleartext.

**Migrations run once, before the rollout.** Not on container boot. A failed
migration fails the deploy and leaves the running version serving traffic.

**Tasks run in public subnets.** Express derives ALB scheme from subnet type,
so private subnets produce an internal ALB with no public URL and drag in a NAT
gateway. Public subnets with a no-ingress security group are cheaper and
simpler; the task is only reachable through the ALB either way.

**No `-target`.** `bootstrap-image.sh` seeds ECR so the service can be created,
which makes the first deploy a single ordinary `terraform apply`.

---

## Costs

About **$20/month** for a shared-mode project: the Fargate task, its public IP,
and a share of an ALB. The database is marginal because the instance is shared.

Fixed platform cost is one RDS instance, about $13/month, spread across every
project on it.

Start at 512 CPU / 1024 MiB and raise on measured CPU, not instinct. See
`skills/deploy/references/cost.md`.

---

## Using it with Claude Code

Install as a plugin, then `/deploy` in any project. The skill reads your config
file, asks whether the app should have a domain and what it should be, and
handles the rest. It will not hardcode account values into your repo.
