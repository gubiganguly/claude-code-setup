---
name: deploy
description: Deploy or redeploy a containerized web app to Amazon ECS Express Mode with Terraform and GitHub Actions, so the first deploy is two commands and every deploy after is a git push. Reads all account-specific settings from a gitignored config file, never from this skill. Asks whether the app should get a custom domain. Use when the user runs /deploy, asks to deploy, ship, redeploy or push-to-prod a project, set up CI/CD to AWS, or stand up hosting on ECS or Fargate.
---

# Deploy to Amazon ECS Express Mode

Stands up (or updates) a production deployment: a container on Fargate behind
an Express-managed ALB, an optional branded domain via CloudFront, a database
on the shared RDS, secrets in Secrets Manager, and a git-push pipeline.

**First deploy:** two commands. **Every deploy after:** `git push`.

## Hard rules

1. **Never hardcode account facts.** Region, account ID, state bucket, platform
   resource names, and hosted zone all come from the config file (Step 0). If a
   value is not there, ask the user and offer to add it. Never paste an account
   ID or internal domain into a committed file, a README, or CLAUDE.md.
2. **Never use local Terraform state.** Every stack uses the S3 backend. Local
   state cannot be locked or shared and stores resource attributes in plaintext.
3. **Never put a secret value in Terraform.** Terraform creates the secret
   container; values are written with `aws secretsmanager put-secret-value`.
   Anything passed as a Terraform variable is stored in state in cleartext.
4. **Always confirm before the first `terraform apply` and before any
   `terraform destroy`.** These create and delete real billable infrastructure.
5. **Never `terraform destroy` the platform stack** unless the user explicitly
   wants the whole account torn down. Every project's database lives on it.

---

## Step 0 — Load config and confirm the target account

```bash
set -a; . ~/.claude/.aws-deploy.env; set +a     # or: . "$DEPLOY_KIT_DIR/scripts/load-config.sh"
aws sts get-caller-identity
```

`$DEPLOY_KIT_DIR` in that file points at the kit. Everything below writes it as
`$DEPLOY_KIT_DIR`; never hardcode the path.

If no config file exists, `load-config.sh` prints the exact commands to create
one. Walk the user through it; do not invent values.

**Verify the account matches.** If `AWS_ACCOUNT_ID` is set in the config and
`get-caller-identity` returns something else, stop and tell the user. Deploying
into the wrong company's account is the one mistake that cannot be quietly
undone.

Confirm tooling: `docker` running, `terraform -version` at least 1.11,
`gh auth status`.

## Step 1 — Decide first-deploy vs redeploy

**Redeploy** if `infra/terraform/` exists AND the service exists:

```bash
aws ecs list-services --cluster "$ECS_CLUSTER_NAME" \
  --query "serviceArns[?contains(@, '/<service>')]"
```

Otherwise it is a first deploy. For a redeploy, skip to Path B.

## Step 2 — Gather inputs (first deploy only)

Derive what you can; ask only for what you cannot.

| Input | How to get it |
|---|---|
| `service_name` | Slugify the repo or directory name. Lowercase, hyphens |
| `github_owner` / `github_repo` | `gh repo view --json owner,name` |
| Runtime secrets | Read `.env` / `.env.example`. Collect the NAMES only |
| Sizing | Default 512 CPU / 1024 MiB. Only raise if the user says the app is heavy |

### Then ask about the domain. Always ask; never assume.

Ask two things, in one question:

> **Should this app have a custom domain?**
> 1. Yes, use the default: `<service>.<HOSTED_ZONE_NAME>`
> 2. Yes, but a different one (ask them to type it)
> 3. No domain, use the AWS-provided `*.on.aws` URL

Guidance to give with the question:

- Recommend a domain for anything a user or customer will open. Raw `*.on.aws`
  URLs have no domain reputation and some corporate mail filters flag them.
- Option 3 is reasonable for a short-lived internal spike.
- A custom domain outside `HOSTED_ZONE_NAME` needs its own Route 53 public
  hosted zone, delegated at the registrar. If they want one, say that
  certificate validation will hang until delegation is done.
- If `HOSTED_ZONE_NAME` is empty in the config, option 1 is unavailable. Say so
  and offer 2 or 3.

Record the answer as `custom_domain` and `hosted_zone_name` in
`terraform.tfvars`. Empty `custom_domain` means no domain, and the whole
CloudFront and ACM path is skipped.

---

## Path A — First deploy

### A1. Make the app container-ready

- `next.config`: add `output: "standalone"`.
- Add a public health route at `/api/health` returning 200. If the app has auth
  middleware or `proxy.ts`, **exclude `/api/health` and `/api/auth`** from its
  matcher, or the service never stabilises.
- **If the app uses Server Actions and will have a custom domain**, add that
  domain to `experimental.serverActions.allowedOrigins`. CloudFront forwards
  the origin host for ALB routing, so Next sees `x-forwarded-host` differing
  from `Origin` and rejects the request as CSRF.
- Copy from the kit (`$DEPLOY_KIT_DIR`):
  - `templates/app/Dockerfile` → `Dockerfile`
  - `templates/app/docker-entrypoint.sh` → `docker-entrypoint.sh`
  - `templates/app/migrate-entrypoint.sh` → `migrate-entrypoint.sh`
  - `templates/ci/deploy.yml` → `.github/workflows/deploy.yml`
  - `terraform/presets/nextjs-prisma/` → `infra/terraform/`
    (or `presets/generic/` for anything not Next.js)

### A2. Configure

- `infra/terraform/main.tf`: set the `backend "s3"` block from
  `$TF_STATE_BUCKET`, with key `$TF_STATE_PREFIX/<service>/terraform.tfstate`.
- `cp terraform.tfvars.example terraform.tfvars`, then fill in: `service_name`,
  `github_*`, the domain answer from Step 2, sizing, and `app_secret_names`
  (names only, never values).
- `.github/workflows/deploy.yml`: set `ECR_REPOSITORY` and `ECS_SERVICE_NAME`
  to the service name, and `AWS_REGION`.

### A3. Deploy

```bash
"$DEPLOY_KIT_DIR"/scripts/bootstrap-image.sh <service> "$AWS_REGION"
cd infra/terraform && terraform init && terraform apply
```

That is the whole first deploy. There is no `-target` step: the bootstrap image
breaks the create-order loop that made v1 need one.

Run long applies with `run_in_background: true` and poll. Check the real
service state rather than trusting the exit code:

```bash
aws ecs describe-express-gateway-service --service-arn "$(terraform output -raw service_arn)"
```

### A4. Set the real secret values

For every name in `app_secret_names`:

```bash
aws secretsmanager put-secret-value \
  --secret-id <service>/<secret-name> \
  --secret-string 'THE_VALUE'
```

Then force a new deployment so tasks pick them up. Never put these values in
`terraform.tfvars`.

### A5. Wire CI and verify

```bash
terraform output -raw gh_variable_commands   # then run what it prints
```

Verify in this order:
1. `curl "$(terraform output -raw express_url)/api/health"` returns 200
2. If a domain was configured, wait for CloudFront (`Status: Deployed`, 5 to 15
   minutes), then curl the branded health URL
3. A real login through the browser

Report `terraform output -raw app_url` as the URL. When a domain exists, that
is the branded one; never hand out the `*.on.aws` URL.

### A6. Commit

Commit the Dockerfile, both entrypoints, the workflow, `infra/terraform/*`, the
health route, and the config changes. `terraform.tfvars` and `*.tfstate*` are
gitignored.

---

## Path B — Redeploy

1. **App or migration change** → commit and push. CI builds, runs migrations as
   a one-shot task, then rolls the service. Watch with
   `gh run watch <id> --exit-status`.
2. **Infrastructure change** → `cd infra/terraform && terraform apply`.
3. **Secret rotation** → `put-secret-value`, then force a new deployment.
4. Always verify after: service stable, health 200, one real user action.

---

## Gotchas

See `references/gotchas.md`. Read it before debugging anything; nearly every
failure in this pipeline is already in that table.

## Cost

See `references/cost.md` for sizing guidance and what each piece actually costs.
The short version: default to 512/1024, use the shared platform, and give a
project its own VPC only when isolation genuinely requires it.
