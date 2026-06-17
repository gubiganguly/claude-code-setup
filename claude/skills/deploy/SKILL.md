---
name: deploy
description: Deploy or redeploy a full-stack web app (Next.js/Node + Postgres) to AWS App Runner — Terraform-provisioned infra plus a GitHub Actions pipeline, so the first deploy is one `terraform apply` and every deploy after is a `git push`. Default SHARED mode (~$5/mo per project) deploys onto the account's standing platform stack (shared VPC/NAT/RDS); DEDICATED mode gives a project its own VPC+RDS. Use when the user runs `/deploy`, asks to deploy/ship/redeploy/push-to-prod a project, set up CI/CD to AWS, or stand up hosting on App Runner.
---

# Deploy to AWS App Runner

This skill stands up (or updates) a production deployment of a containerized
full-stack app on **AWS App Runner**, fronting **RDS PostgreSQL**, provisioned by
**Terraform** and shipped by a **GitHub Actions + OIDC** pipeline. Outcome:

- **First deploy:** one `terraform apply` → a live HTTPS URL, DB created + seeded.
- **Every deploy after:** `git push` → Actions builds the image and rolls the
  service; **DB migrations + seeds run automatically inside the container on boot**.

It is generic — works for any project that builds to a Node server container and
uses Prisma + Postgres. Templates live in `templates/` next to this file; they are
the already-debugged, working versions. Copy and adapt them — don't reinvent.

## Two infrastructure modes

- **SHARED (default for new projects).** The account has a standing platform
  stack (`~/Development/aws-platform/terraform`): one VPC (`10.10.0.0/16`), one
  NAT, one RDS Postgres (`platform-db`), one App Runner VPC connector
  (`platform-shared`). A project deploy creates ONLY per-project pieces: ECR
  repo, App Runner service, secrets, OIDC role, and a database + role on the
  shared RDS. Marginal cost ≈ $5/mo per project. Use `templates/terraform-shared/`.
- **DEDICATED.** The project gets its own VPC + NAT + RDS (~$50/mo). Use
  `templates/terraform/`. Choose this only when the user asks for isolation or
  the app handles sensitive/production-critical data — or to "graduate" an app
  off the shared instance.

Detect: shared platform exists if `aws ec2 describe-vpcs --filters
Name=tag:Name,Values=platform-vpc` returns a VPC. If it doesn't, either deploy
dedicated or (with user confirmation) stand the platform up first by applying
`~/Development/aws-platform/terraform`.

---

## Step 0 — Detect mode and gather context

1. Confirm tooling: `aws sts get-caller-identity` (right account?), `docker` running,
   `terraform -version` (≥1.6), `gh auth status`. If AWS has no usable default
   profile but a named one exists, copy it to default (or set `AWS_PROFILE`).
2. **Decide the mode:**
   - **FIRST DEPLOY** if `infra/terraform/` is absent OR there's no App Runner
     service yet (`aws apprunner list-services` has no service named `<project>`).
   - **REDEPLOY** otherwise.
3. Gather inputs (ask only if not obvious):
   - `<project>` — short slug (derive from repo/dir name; lowercased).
   - GitHub `owner/repo` (from `git remote -v` / `gh repo view`).
   - Region (default `us-east-1`).
   - The app's **runtime secrets/env** (read `.env` / `.env.example`): DB url is
     handled automatically; everything else (auth secret, API keys) becomes a
     Secrets Manager entry + an App Runner env var.
   - **Shared mode:** the platform VPC connector ARN
     (`aws apprunner list-vpc-connectors --query "VpcConnectors[?VpcConnectorName=='platform-shared'].VpcConnectorArn" --output text`).
   - **Dedicated mode only:** a **unique VPC CIDR** (`10.X.0.0/16`) — pick an X
     not used by another VPC in the account (`10.10` is the platform; csip uses
     `10.30`, lbmc `10.20`, dice `10.40`).

---

## Path A — FIRST DEPLOY

### A1. Make the app container-ready
- `next.config`: add `output: "standalone"`.
- Add a public health route `src/app/api/health/route.ts` (copy `templates/app/health-route.ts`).
- If the app has auth middleware/`proxy.ts`, **exclude `/api/health` and `/api/auth`** from its matcher.
- **Make every seed script idempotent** (guard: "if base record exists, return") — they run on every boot.
- Copy into the repo root: `templates/Dockerfile` → `Dockerfile`,
  `templates/docker-entrypoint.sh` → `docker-entrypoint.sh`,
  `templates/dockerignore` → `.dockerignore`,
  `templates/deploy.yml` → `.github/workflows/deploy.yml`.
- Copy the terraform templates → `infra/terraform/` (rename `gitignore` →
  `.gitignore`, keep `terraform.tfvars.example`):
  **shared mode → `templates/terraform-shared/`** (includes `create-db.sh`;
  keep it executable), **dedicated mode → `templates/terraform/`**.

### A2. Adapt the templates to this app
- `infra/terraform/variables.tf`: set `project_name` default to `<project>`,
  `github_owner`/`github_repo`/`github_branch`. Replace the app-specific secret
  vars (the template has `anthropic_api_key`) with whatever THIS app needs (one
  `variable` per required API key, `sensitive = true`).
- `infra/terraform/secrets.tf`: keep the auto-composed `database_url`/`direct_url`
  + `auth-secret`; add/remove app secrets to match this app's env. **Keep the
  `urlencode(...)` around the DB password.**
- `infra/terraform/apprunner.tf`: set `runtime_environment_secrets` (the app
  secrets' ARNs) and `runtime_environment_variables` (non-secret env, e.g.
  `AUTH_TRUST_HOST=true`, `NODE_ENV=production`) to match this app. Keep `port=3000`,
  health path `/api/health`, and the instance-role policy reading exactly the
  secrets used.
- **Dedicated mode only** — `infra/terraform/network.tf`: change the CIDR +
  subnet CIDRs to the unique `10.X`, and set `db_name`/`db_username` in variables.
- **Shared mode** — nothing else: the db name/role derive from `project_name`
  (`db.tf`), and `terraform.tfvars` carries `platform_vpc_connector_arn`.
- `infra/terraform/domain.tf`: gives the app `<project>.apps.snhcap.com` (zone
  owned by the platform stack, delegated from GoDaddy). Works as-is; delete the
  file only if the project shouldn't get a custom domain. Share the custom
  domain, never the raw `*.awsapprunner.com` URL — Microsoft Defender flags
  the latter as suspicious.
- `.github/workflows/deploy.yml`: set `ECR_REPOSITORY` and `APP_RUNNER_SERVICE_NAME`
  to `<project>`; ensure `docker-entrypoint.sh` is in the `paths:` filter.
- `docker-entrypoint.sh`: keep `migrate deploy` → idempotent seeds → `export
  HOSTNAME=0.0.0.0` → `node server.js`. Adjust the seed list to this project's seed files.

### A3. Provision + deploy (run from `infra/terraform/`)
```bash
cp terraform.tfvars.example terraform.tfvars     # set project_name, github_*, API keys
terraform init
terraform apply -target=aws_ecr_repository.app   # ECR FIRST (App Runner needs an image)
```
Shared-mode note: `terraform apply` runs `create-db.sh` against the shared RDS
public endpoint — the operator's IP must be in the platform stack's
`admin_cidrs`. If psql times out, update `admin_cidrs` in
`~/Development/aws-platform/terraform/terraform.tfvars` and re-apply the
platform first. Shared-mode applies take ~3 min (no RDS/VPC to create).
Then build + push the first image (from repo root):
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT_ID.dkr.ecr.<region>.amazonaws.com/<project>"
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin "${ECR%/*}"
docker buildx build --platform linux/amd64 -t "$ECR:latest" --push .   # amd64 is MANDATORY
```
Then the full apply (≈15–20 min; RDS is the long pole):
```bash
cd infra/terraform && terraform apply
```
Run long applies with `run_in_background: true` and poll — RDS + App Runner exceed
a 10-min foreground limit. **Check the real App Runner status, not terraform's exit
code** (`aws apprunner list-services …`).

### A4. Custom domain (two-phase — the validation records don't exist until
the association does, so a single apply fails with "Invalid for_each argument"):
```bash
terraform apply -target=aws_apprunner_custom_domain_association.app
terraform apply        # creates the validation CNAMEs + the domain CNAME
```
Cert issuance takes ~5–15 min after the records land. Poll until
`CustomDomains[0].Status` is `active`:
`aws apprunner describe-custom-domains --service-arn <arn>`.

### A5. Wire git-push deploys + verify
- `gh variable set AWS_DEPLOY_ROLE_ARN --body "<github_actions_role_arn output>" --repo <owner>/<repo>`
- Verify: `curl <app_url>/api/health` → 200, and once the domain is active,
  `curl https://<project>.apps.snhcap.com/api/health` → 200; then a real login
  (use Playwright if available). Container logs are in CloudWatch
  `/aws/apprunner/<project>/<service-id>/application`.
- Report the custom domain as THE app URL.

### A6. Commit everything
Commit the new deploy files (Dockerfile, entrypoint, .dockerignore, workflow,
`infra/terraform/*`, next.config, health route, idempotent seeds) and push.
`terraform.tfvars` and `*.tfstate*` are gitignored — never commit them or secrets.
The locally-built image and the repo must match, or the next CI build ships stale code.

---

## Path B — REDEPLOY (after changes)

1. **App code / Dockerfile / migrations changed** → just commit and `git push`.
   GitHub Actions builds the image, pushes to ECR, calls `apprunner start-deployment`,
   and waits for RUNNING. Migrations + seeds run in the container on boot.
   Watch it: `gh run watch <id> --repo <owner>/<repo> --exit-status`.
   *(Manual fallback without CI: `docker buildx build --platform linux/amd64 -t <ECR>:latest --push .` then `aws apprunner start-deployment --service-arn <arn>`.)*
2. **Infrastructure (`*.tf`) changed** → `cd infra/terraform && terraform apply`.
3. **Schema changed** → nothing extra; the container runs `migrate deploy` on the
   next boot. (Migrations are committed in `prisma/migrations/`.)
4. Always verify after: App Runner `RUNNING` + `/api/health` 200 + a quick login.

---

## Gotchas — these WILL bite; the templates already fix them, keep them fixed

| Symptom | Cause | Fix |
|---|---|---|
| apply fails creating App Runner: "no image" | needs image at create time | ECR-first `-target` apply, push image, *then* full apply |
| `exec format error` on App Runner | image built arm64 | `docker buildx build --platform linux/amd64` always |
| migrate `P1013 invalid port number` | RDS password has special chars | `urlencode(local.rds_master_password)` in secrets.tf |
| apply: OIDC provider "already exists" | account already has the GitHub OIDC provider | use `data "aws_iam_openid_connect_provider"`, don't create one |
| `CREATE_FAILED`; logs show server bound to `ip-…ec2.internal` | App Runner overrides `HOSTNAME` | `export HOSTNAME=0.0.0.0` in entrypoint before `node server.js` |
| app reaches RDS but not the internet | VPC connector on public subnets | put connector on **private** subnets (NAT egress) |
| `/api/health` returns 307 | auth middleware gating it | exclude `/api/health` from the matcher |
| migrate/seed not running on deploy | standalone image omits Prisma CLI | overlay full `node_modules` + copy `prisma/`, `prisma.config.ts`, `src/generated` (Dockerfile does this) |
| "state locked" after a killed apply | stale local lock | delete `.terraform.tfstate.lock.info` (or `terraform force-unlock <id>`) |
| re-apply: service "already exists" | orphaned `CREATE_FAILED` service not in state | `aws apprunner delete-service --service-arn …`, then apply |
| CI deploys but the run goes **red** on "Resolve service ARN" with `apprunner:ListServices ... not authorized` | OIDC role only granted `StartDeployment` | grant the GitHub role `apprunner:ListServices` on `*` **and** `apprunner:DescribeService` on the service ARN (oidc.tf already does) |
| Next 16: middleware deprecated | renamed | use `proxy.ts` (same level as `app/`) |
| first apply: `Invalid for_each argument` in domain.tf | validation records unknown until association exists | two-phase: `-target` the domain association, then full apply |
| custom domain stuck `pending_certificate_dns_validation` | validation CNAMEs missing/wrong, or GoDaddy NS delegation for apps.snhcap.com broken | check `dig NS apps.snhcap.com` returns the Route 53 name servers |
| Microsoft Defender "might not be safe" on app link | raw `*.awsapprunner.com` URL has no domain reputation | always share `<project>.apps.snhcap.com`; optionally have M365 admin allowlist `*.apps.snhcap.com` |
| `timeout while waiting for plugin to start` / terraform hangs forever (Apple Silicon) | x86_64 terraform+providers crashing Rosetta (`arm_interval` assertion in TF_LOG=TRACE) | use the darwin_arm64 terraform binary, then `rm -rf .terraform && terraform init -upgrade` per project; beware Intel-prefix (`/usr/local`) Homebrew reinstalling the x86 one on upgrade |

---

## Cost & teardown
- **Shared mode:** marginal cost ≈ $5/mo per project (App Runner idle memory).
  The platform's fixed ~$45/mo (NAT + RDS) is paid once for all projects.
  Tear down a project with `terraform destroy` in ITS `infra/terraform/` — this
  removes the service/ECR/secrets but **not** the project's database on the
  shared RDS (drop it manually with psql if the data should go too).
- **Dedicated mode:** RDS + NAT ≈ $50/mo per project. `terraform destroy`
  removes everything including the data.
- **NEVER run destroy in `~/Development/aws-platform/terraform`** unless the
  user explicitly wants the whole platform gone — every shared-mode project's
  database lives on it (RDS has deletion protection + final snapshot as backstops).
- Rotate any API keys placed in `terraform.tfvars` before real production use.

## Python backend (`/backend` FastAPI)
If the repo also has a `/backend` FastAPI service, deploy it as a SECOND App
Runner service alongside the frontend one (shared mode keeps this cheap):
- Duplicate the `ecr.tf` + `apprunner.tf` resources with a `-backend` suffix
  (`<project>-backend`), port `8000`, health path `/health` (add the endpoint
  to FastAPI), and a Dockerfile running
  `uvicorn src.main:app --host 0.0.0.0 --port 8000`.
- Backend migrations: Alembic in the entrypoint (`alembic upgrade head`) before
  starting uvicorn; it reuses the same `DATABASE_URL` secret (use
  `postgresql+psycopg://` form for SQLAlchemy — add a second secret if needed).
- Point the frontend at it with a non-secret env var (e.g.
  `BACKEND_URL=https://<backend service_url>`), and add the second service to
  the GitHub workflow (second build + `start-deployment`).

## Notes
- One AWS account hosts many projects: unique `project_name` each; dedicated
  mode also needs a unique VPC CIDR.
- A full reference write-up also lives at `~/Desktop/AWS-AppRunner-Deployment-Playbook.md`.
- Confirm with the user before the first `terraform apply` and before `terraform
  destroy` — these create/delete real billable infrastructure.
