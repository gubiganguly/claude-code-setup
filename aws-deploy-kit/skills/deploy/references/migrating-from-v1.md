# Migrating a v1 project to v2

v1 projects keep working. Nothing here is urgent except step 1, which is.

## 1. Move state to S3 (do this first, for every project)

v1 kept Terraform state in a local file. That means one laptop is a single
point of failure for the whole estate, there is no locking, and generated
passwords sit in cleartext on disk.

Per project, after the bootstrap stack exists:

```bash
cd <project>/infra/terraform

cp terraform.tfstate terraform.tfstate.pre-migration.bak   # keep until verified

# Add the backend block to main.tf:
#   backend "s3" {
#     bucket       = "<TF_STATE_BUCKET>"
#     key          = "projects/<service>/terraform.tfstate"
#     region       = "<AWS_REGION>"
#     encrypt      = true
#     use_lockfile = true
#   }

terraform init -migrate-state    # answer "yes" when it offers to copy
terraform plan                   # MUST be "No changes"
```

`terraform plan` showing no changes is the proof the migration worked. If it
wants to create things that already exist, stop and check the `key` path.

Once verified across all projects:

```bash
find ~/Portcos -name "terraform.tfstate*" -not -path "*/.terraform/*" -delete
```

## 2. Rotate the credentials that were in local state

Anything Terraform generated in v1 was written to disk in cleartext. Treat all
of it as exposed:

```bash
# Database passwords: re-run the provisioner with a new password.
terraform taint 'module.database.random_password.db' && terraform apply

# Auth signing keys: force a new value (this logs everyone out).
terraform taint 'random_password.auth_secret' && terraform apply
```

Any API key that was passed through `terraform.tfvars` should be rotated at the
provider and re-set with `put-secret-value`.

## 3. Optional: adopt the v2 layout

Only worth doing when a project is being actively worked on.

| v1 | v2 |
|---|---|
| `templates/terraform-shared/` copied wholesale | `presets/nextjs-prisma/` calling shared modules |
| `-target` twice on first apply | `bootstrap-image.sh` then one `terraform apply` |
| Migrations and seeds on container boot | Migration task in CI; seeds behind `RUN_SEEDS` |
| API keys as Terraform variables | Secret containers in TF, values via `put-secret-value` |
| `db.tf` running psql from your laptop | `modules/database` running it inside the VPC |
| Domain hardcoded to one zone | `custom_domain` + `hosted_zone_name`, or none at all |
| ECR expiring untagged images only | Expires old tagged images too |
| No task role | Task role always created |

The safest path is not an in-place rewrite. Stand the project up fresh under
v2 with a different `service_name`, verify it, repoint DNS, then destroy the
old stack. The database lives on the shared instance and is not touched by
either stack, so the data survives the switch.

## 4. Platform stack

The v2 platform makes RDS private and drops the NAT gateway. On an existing
platform, do this in order:

1. Migrate every project to v2 database provisioning (in-VPC), or confirm that
   nothing still relies on reaching RDS from a laptop.
2. Move any service still running in private subnets into public ones.
3. Only then set `publicly_accessible = false` and remove the NAT.

Doing step 3 first will break database provisioning for any project still on
v1, because v1 psql's in from outside the VPC.
