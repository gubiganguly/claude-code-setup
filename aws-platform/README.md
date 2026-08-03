# AWS Shared Deployment Platform

The standing, fixed-cost infrastructure that every small project deploys onto
via the `/deploy` skill (shared mode). One of these per AWS account
(346698404534, us-east-1).

> New to the setup? Read [ARCHITECTURE.md](ARCHITECTURE.md) first, a
> plain-English, end-to-end explanation of every service involved.

## What it provides

| Resource | Name | Purpose |
|---|---|---|
| VPC | `platform-vpc` (10.10.0.0/16) | Network for all shared-mode projects |
| Public subnets | `platform-public-0/1` | Where ECS Express tasks and `platform-db` run; egress via the internet gateway |
| Private subnets | `platform-private-0/1` | Retained but not used by Express deploys; route out via the NAT |
| NAT gateway | `platform-nat` | Outbound internet for the private subnets only. Express tasks do not use it. |
| RDS Postgres 17 | `platform-db` (db.t4g.micro) | One database + role per project |
| Shared egress SG | `platform-ecs-egress` | Attached to every project's tasks; the SG that `platform-rds-sg` trusts for Postgres |
| RDS SG | `platform-rds-sg` | Opens 5432 only to `platform-ecs-egress` and the operator IPs in `admin_cidrs` |
| Route 53 zone | `apps.snhcap.com` | Custom domains: each project gets `<project>.apps.snhcap.com` (delegated from GoDaddy via NS records; if the zone is ever recreated, update those NS records) |
| *(legacy)* App Runner VPC connector | `platform-shared` | Unused leftover from the App Runner era. Nothing depends on it. |

Load balancers do not appear here on purpose: ECS Express creates and manages
them itself and shares them across services, so they belong to no single
project's Terraform.

## What it actually costs

Earlier versions of this file estimated "~$45/month fixed plus ~$5/month per
project." **That estimate is wrong and predates the ECS Express migration.**
Actual unblended spend for July 2026, with 12 services deployed:

| Service | July 2026 |
|---|---|
| Elastic Container Service (Fargate tasks) | $224.33 |
| Virtual Private Cloud (NAT hourly + data) | $75.38 |
| Elastic Load Balancing (Express-managed ALBs) | $67.44 |
| Relational Database Service (`platform-db`) | $57.52 |
| EC2 – Other | $36.71 |
| EC2 – Compute | $30.95 |
| Secrets Manager | $9.31 |
| CloudWatch | $6.09 |
| ECR | $0.96 |
| Route 53 | $0.51 |
| Tax | $33.63 |
| **Total** | **$543.07** |

Read that as roughly **$500 to $550/month for the whole account** at 12
services, not ~$105. The three things worth knowing:

- **Fargate is the biggest line.** Express tasks bill for the vCPU and memory
  they are sized for, continuously, whether or not anyone is using the app.
  Right-sizing `app_cpu` / `app_memory` per project is the highest-leverage
  cost lever available.
- **Load balancers are not free.** Express provisions ALBs in the account and
  standard ALB pricing applies. They are shared across services, so the cost
  does not scale one-per-project, but it is real.
- **The NAT still costs money** even though Express tasks egress through the
  internet gateway instead. Confirm what still routes through the private
  subnets before assuming it can be removed.

Re-check the current numbers rather than trusting this table:

```bash
aws ce get-cost-and-usage --time-period Start=<YYYY-MM-01>,End=<YYYY-MM-01> \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE --output json
```

## How projects use it

Run `/deploy` in a project. It copies the skill's `terraform-shared` templates
into the project's `infra/terraform/`, which look up `platform-db` and the
shared egress security group by name, create the project's database and role on
the shared instance, and stand up the project's own ECR repo, ECS Express
service, secrets, CloudFront distribution, branded domain, and CI role. No
per-project VPC, NAT, or connector is created.

## Operating it

```bash
cd terraform
terraform apply        # after editing terraform.tfvars or *.tf
terraform output       # RDS endpoint, master secret ARN, subnet + SG ids
```

- **Your IP changed?** Update `admin_cidrs` in `terraform.tfvars` and re-apply.
  Needed for `/deploy` to reach the database for provisioning and migrations.
  Never widen it to `0.0.0.0/0`: it is the only network-layer protection on the
  database (see Networking, honestly in ARCHITECTURE.md).
- **DB admin access:** master credentials are in Secrets Manager (ARN from
  `terraform output rds_master_secret_arn`). Apps never use them.
- **Instance getting busy?** Bump `db_instance_class` to `db.t4g.small`, or
  graduate the heavy project to a dedicated stack (`/deploy` dedicated mode)
  and `pg_dump` / `pg_restore` its database over.
- **A project's costs look high?** Check its `app_cpu` and `app_memory` first.
  Idle Fargate capacity is the usual culprit.

## State

The local `terraform.tfstate` in `terraform/` is the source of truth and is
deliberately not committed anywhere.

**This is a single point of failure.** This directory is not a git repository,
and the state file exists only on the operator's Mac. If that machine is lost,
the AWS infrastructure keeps running but nobody can manage it with Terraform
without importing every resource by hand. Back the state file up somewhere
durable, or move it to an S3 backend with locking.

## Never

- `terraform destroy` here while any project still runs on the platform. Every
  shared-mode project's database lives on `platform-db`. (Deletion protection
  and a final snapshot are enabled as backstops.)
