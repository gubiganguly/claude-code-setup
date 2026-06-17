# AWS Shared Deployment Platform

The standing, fixed-cost infrastructure that every small project deploys onto
via the `/deploy` skill (shared mode). One of these per AWS account
(346698404534, us-east-1).

> New to the setup? Read [ARCHITECTURE.md](ARCHITECTURE.md) first — a
> plain-English, end-to-end explanation of every service involved.

## What it provides

| Resource | Name | Purpose |
|---|---|---|
| VPC | `platform-vpc` (10.10.0.0/16) | Network for all shared-mode projects |
| NAT gateway | `platform-nat` | Outbound internet for App Runner services |
| RDS Postgres 17 | `platform-db` (db.t4g.micro) | One database + role per project |
| App Runner VPC connector | `platform-shared` | Reused by every project's service |
| Route 53 zone | `apps.snhcap.com` | Custom domains: each project gets `<project>.apps.snhcap.com` (delegated from GoDaddy via NS records — if the zone is ever recreated, update those NS records) |

Fixed cost ≈ **$45/month total** (NAT ~$32, RDS ~$13). Each project deployed on
it adds only its own App Runner service (~$5/month idle).

## How projects use it

Run `/deploy` in a project — it copies the skill's `terraform-shared` templates
into the project's `infra/terraform/`, which look up `platform-db` and the
connector by name, create the project's database/role on the shared instance,
and stand up the project's own ECR repo + App Runner service + secrets + CI role.

## Operating it

```bash
cd terraform
terraform apply        # after editing terraform.tfvars or *.tf
terraform output       # connector ARN, RDS endpoint, master secret ARN
```

- **Your IP changed?** Update `admin_cidrs` in `terraform.tfvars`, re-apply.
  (Needed for /deploy to reach the DB for provisioning/migrations.)
- **DB admin access:** master creds are in Secrets Manager (ARN from
  `terraform output rds_master_secret_arn`). Apps never use them.
- **Instance getting busy?** Bump `db_instance_class` to `db.t4g.small`, or
  graduate the heavy project to a dedicated stack (`/deploy` dedicated mode)
  and `pg_dump`/`pg_restore` its database over.
- **State:** local `terraform.tfstate` in `terraform/` is the source of truth —
  don't delete it.

## Never

- `terraform destroy` here while any project still runs on the platform —
  every shared-mode project's database lives on `platform-db`. (Deletion
  protection and a final snapshot are enabled as backstops.)
