---
name: deploy
description: Deploy or redeploy a full-stack web app (Next.js/Node + Postgres) to Amazon ECS Express Mode — Terraform-provisioned infra plus a GitHub Actions pipeline, so the first deploy is one `terraform apply` and every deploy after is a `git push`. Default SHARED mode (onto the account's standing platform VPC/RDS) keeps per-project cost low; DEDICATED mode gives a project its own VPC+RDS. A branded `<project>.apps.snhcap.com` domain is served via CloudFront in front of the Express service. Use when the user runs `/deploy`, asks to deploy/ship/redeploy/push-to-prod a project, set up CI/CD to AWS, or stand up hosting on ECS / Fargate.
---

# Deploy to Amazon ECS Express Mode

This skill stands up (or updates) a production deployment of a containerized
full-stack app on **Amazon ECS Express Mode** (Fargate behind an
auto-provisioned, shared Application Load Balancer), fronting **RDS PostgreSQL**,
provisioned by **Terraform** and shipped by a **GitHub Actions + OIDC** pipeline.

> **Why ECS Express Mode, not App Runner?** AWS stopped accepting new App Runner
> customers on **April 30, 2026** (no new features) and recommends **ECS Express
> Mode** for containerized apps. Existing App Runner services keep running, but
> all new deploys go to Express Mode. A single `aws_ecs_express_gateway_service`
> resource provisions the Fargate task, ALB + HTTPS listener + ACM cert, target
> group, security groups, autoscaling, and an AWS-provided `*.on.aws` URL.

Outcome:

- **First deploy:** `terraform apply` (a few targeted phases) → a live HTTPS URL,
  DB created + seeded, branded domain via CloudFront.
- **Every deploy after:** `git push` → Actions builds the image, pushes to ECR,
  and the official `aws-actions/amazon-ecs-deploy-express-service` action rolls
  the service and waits for it to stabilize. **DB migrations + idempotent seeds
  run automatically inside the container on boot.**

It is generic — works for any project that builds to a Node server container and
uses Prisma + Postgres. Templates live in `templates/` next to this file; they are
the already-debugged, working versions (validated against AWS provider v6.23+).
Copy and adapt them — don't reinvent.

## Two infrastructure modes

- **SHARED (default for new projects).** The account has a standing platform
  stack (`~/Development/aws-platform/terraform`): one VPC (`10.10.0.0/16`) with
  public + private subnets, an IGW, and one RDS Postgres (`platform-db`). A
  project deploy creates ONLY per-project pieces: ECR repo, ECS Express service,
  secrets, IAM roles, OIDC role, a database + role on the shared RDS, plus
  ACM/CloudFront for the domain. ECS Express tasks run in the platform's
  **public** subnets and share one ALB across services (≤25 per VPC). Use
  `templates/terraform-shared/`.
- **DEDICATED.** The project gets its own VPC + RDS. Use `templates/terraform/`.
  Choose this only when the user asks for isolation or the app handles
  sensitive/production-critical data. **No NAT gateway** — public-subnet tasks
  egress via the IGW (a ~$32/mo saving vs the old App Runner dedicated stack).

Detect: shared platform exists if `aws ec2 describe-vpcs --filters
Name=tag:Name,Values=platform-vpc` returns a VPC. If it doesn't, either deploy
dedicated or (with user confirmation) stand the platform up first.

### One-time platform prerequisite (SHARED mode)

ECS Express tasks need a security group that the shared RDS trusts. The platform
RDS SG (`platform-rds-sg`) currently trusts only the App Runner egress SG. Add a
dedicated ECS task SG once (additive, safe — does not touch live App Runner
services), in `~/Development/aws-platform/terraform`:

- `aws_security_group "ecs_egress"` named `platform-ecs-egress` (no ingress,
  egress all),
- a `platform-rds-sg` ingress rule for port 5432 from that SG,
- an output `ecs_egress_sg_id`.

Then `terraform apply` the platform once. Projects consume `public_subnet_ids`
and `ecs_egress_sg_id` from the platform outputs. (Mirrors exactly how the
shared App Runner VPC connector was provisioned.)

---

## Step 0 — Detect mode and gather context

1. Confirm tooling: `aws sts get-caller-identity` (right account?), `docker` running,
   `terraform -version` (**≥1.6; AWS provider is pinned `~> 6.23`** — the Express
   resource was added in v6.23.0), `gh auth status`. If AWS has no usable default
   profile but a named one exists, copy it to default (or set `AWS_PROFILE`).
2. **Decide the mode:**
   - **FIRST DEPLOY** if `infra/terraform/` is absent OR there's no Express service
     yet (`aws ecs list-services --cluster default --query "serviceArns[?contains(@, '/<project>')]"` is empty).
   - **REDEPLOY** otherwise.
3. Gather inputs (ask only if not obvious):
   - `<project>` — short slug (derive from repo/dir name; lowercased).
   - GitHub `owner/repo` (from `git remote -v` / `gh repo view`).
   - Region (default `us-east-1`).
   - The app's **runtime secrets/env** (read `.env` / `.env.example`): DB url is
     handled automatically; everything else (auth secret, API keys) becomes a
     Secrets Manager entry + an Express container `secret`.
   - **Shared mode:** the platform public subnet IDs and the ECS egress SG ID:
     `cd ~/Development/aws-platform/terraform && terraform output -json public_subnet_ids`
     and `terraform output -raw ecs_egress_sg_id` (apply the §prereq first if absent).
   - **Dedicated mode only:** a **unique VPC CIDR** (`10.X.0.0/16`) — pick an X
     not used by another VPC (`10.10` platform; csip `10.30`, lbmc `10.20`, dice `10.40`).

---

## Path A — FIRST DEPLOY

### A1. Make the app container-ready
- `next.config`: add `output: "standalone"`.
- **If the app uses Server Actions (most Next apps do):** add the branded domain
  to `experimental.serverActions.allowedOrigins` in `next.config`
  (`["<project>.apps.snhcap.com"]`). CloudFront forwards the origin (`*.on.aws`)
  host for ALB routing, so the request's `x-forwarded-host` differs from the
  branded `Origin` — Next rejects that as CSRF ("Invalid Server Actions request")
  unless the branded origin is allowlisted. (App Runner didn't rewrite Host, so
  this is new with the CloudFront-in-front pattern.)
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
- `infra/terraform/variables.tf`: set `project_name`, `github_owner`/`github_repo`/
  `github_branch`. Replace the app-specific secret vars (template has
  `anthropic_api_key`) with whatever THIS app needs (one `variable` per key,
  `sensitive = true`). `app_cpu`/`app_memory` are **numeric Fargate units**
  (`"1024"` CPU / `"2048"` MiB by default) — not App Runner's `"1 vCPU"` strings.
- `infra/terraform/secrets.tf`: keep the auto-composed `database_url`/`direct_url`
  + `auth-secret`; add/remove app secrets to match this app's env. **Keep the
  `urlencode(...)` around the DB password.**
- `infra/terraform/ecs.tf`: set the `primary_container` `environment {}` (non-secret
  env, e.g. `AUTH_TRUST_HOST`, `NODE_ENV`) and `secret {}` blocks (the app secrets'
  ARNs) to match this app, and keep the execution-role secrets policy reading
  exactly those secrets. Keep `container_port = 3000`, `health_check_path =
  "/api/health"`, and the `lifecycle { ignore_changes = [primary_container[0].image] }`
  (CI owns the rolling image tag).
- **Dedicated mode only** — `infra/terraform/network.tf`: change the CIDR + subnet
  CIDRs to the unique `10.X`, and set `db_name`/`db_username` in variables.
- **Shared mode** — set `platform_public_subnet_ids` + `platform_ecs_security_group_id`
  in `terraform.tfvars` (from the platform outputs above). The db name/role derive
  from `project_name` (`db.tf`).
- `infra/terraform/domain.tf`: gives the app `<project>.apps.snhcap.com` via
  CloudFront (ACM cert + Route 53 alias, origin = the Express `*.on.aws` URL).
  Works as-is; delete the file only if the project shouldn't get a branded domain.
  **Always share the custom domain, never the raw `*.on.aws` URL** — it has no
  domain reputation and Microsoft Defender flags raw AWS URLs.
- `.github/workflows/deploy.yml`: set `ECR_REPOSITORY` and `ECS_SERVICE_NAME` to
  `<project>`; ensure `docker-entrypoint.sh` is in the `paths:` filter.
- `docker-entrypoint.sh`: keep `migrate deploy` → idempotent seeds → `export
  HOSTNAME=0.0.0.0` → `node server.js`. Adjust the seed list to this project's seed files.

### A3. Provision + deploy (run from `infra/terraform/`)
The Express service needs an image in ECR at create time, and the CloudFront origin
needs the Express URL (only known after the service exists), so the first deploy is
phased:
```bash
cp terraform.tfvars.example terraform.tfvars     # set project_name, github_*, subnets/SG, API keys
terraform init
terraform apply -target=aws_ecr_repository.app    # ECR FIRST
```
Build + push the first image (from repo root):
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT_ID.dkr.ecr.<region>.amazonaws.com/<project>"
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin "${ECR%/*}"
docker buildx build --platform linux/amd64 -t "$ECR:latest" --push .   # amd64 is MANDATORY (Fargate x86_64)
```
Create the Express service (this also provisions secrets, IAM roles, and — shared
mode — the project DB), then create the domain:
```bash
cd infra/terraform
terraform apply -target=aws_ecs_express_gateway_service.app   # service + its deps
terraform apply                                               # ACM + CloudFront + Route 53 (needs the Express URL)
```
Run long applies with `run_in_background: true` and poll. **Check the real service
status, not terraform's exit code** (get the ARN from `terraform output -raw service_arn`):
`aws ecs describe-express-gateway-service --service-arn <service_arn>`.
Shared-mode note: the service apply runs `create-db.sh` against the shared RDS
public endpoint — the operator's IP must be in the platform stack's `admin_cidrs`.

### A4. Domain + cert (CloudFront)
The final `terraform apply` issues the ACM cert (DNS-validated in the
`apps.snhcap.com` Route 53 zone) and creates the CloudFront distribution. Cert
validation takes a few minutes; CloudFront takes ~5–15 min to deploy. Poll:
```bash
aws cloudfront get-distribution --id <id> --query "Distribution.Status"   # → Deployed
```
If the Express URL didn't auto-resolve into the CloudFront origin (a derivation
edge case), read it and pass it explicitly:
`aws ecs describe-express-gateway-service --service-arn $(terraform output -raw service_arn)`
→ set `express_origin_host` in `terraform.tfvars` (bare host, no scheme) and re-apply.

### A5. Wire git-push deploys + verify
- Set the repo variables (Settings → Secrets and variables → Actions → Variables):
  - `AWS_DEPLOY_ROLE_ARN` ← `terraform output github_actions_role_arn`
  - `AWS_ECS_EXECUTION_ROLE_ARN` ← `terraform output execution_role_arn`
  - `AWS_ECS_INFRA_ROLE_ARN` ← `terraform output infra_role_arn`
  (`gh variable set NAME --body "<value>" --repo <owner>/<repo>`)
- Verify: `curl https://<express on.aws url>/api/health` → 200, and once CloudFront
  is Deployed, `curl https://<project>.apps.snhcap.com/api/health` → 200; then a
  real login (use Playwright if available). Container logs are in CloudWatch
  `/ecs/<project>`.
- Report the custom domain as THE app URL.

### A6. Commit everything
Commit the new deploy files (Dockerfile, entrypoint, .dockerignore, workflow,
`infra/terraform/*`, next.config, health route, idempotent seeds) and push.
`terraform.tfvars` and `*.tfstate*` are gitignored — never commit them or secrets.
The locally-built image and the repo must match, or the next CI build ships stale code.

---

## Path B — REDEPLOY (after changes)

1. **App code / Dockerfile / migrations changed** → just commit and `git push`.
   GitHub Actions builds the image, pushes to ECR, and the
   `aws-actions/amazon-ecs-deploy-express-service@v1` step updates the service to
   the new image and **waits for the deployment to stabilize**. Migrations + seeds
   run in the container on boot. Watch it: `gh run watch <id> --repo <owner>/<repo> --exit-status`.
   *(Manual fallback without CI: `docker buildx build --platform linux/amd64 -t <ECR>:<sha> --push .` then re-run the action via `workflow_dispatch`, or
   `aws ecs update-express-gateway-service --service-arn $(terraform output -raw service_arn) --primary-container image=<ECR>:<sha>`.)*
2. **Infrastructure (`*.tf`) changed** → `cd infra/terraform && terraform apply`.
   (Terraform ignores the image tag, so it won't fight CI over the running image.)
3. **Schema changed** → nothing extra; the container runs `migrate deploy` on the
   next boot. (Migrations are committed in `prisma/migrations/`.)
4. Always verify after: service stable + `/api/health` 200 + a quick login.

---

## Gotchas — these WILL bite; the templates already fix them, keep them fixed

| Symptom | Cause | Fix |
|---|---|---|
| `terraform init`: no `aws_ecs_express_gateway_service` | AWS provider too old | pin `aws ~> 6.23` (resource added in provider v6.23.0) |
| validate: "Blocks of type X are not expected here" on `network_configuration`/`scaling_target`/`aws_logs_configuration` | these are nested-object **attributes**, not blocks | use assignment syntax: `network_configuration = [{ … }]` (templates already do) |
| app has no public URL / only reachable internally | tasks placed in **private** subnets → Express makes an **internal** ALB | always use **public** subnets in `network_configuration` |
| `exec format error` on the task | image built arm64 | `docker buildx build --platform linux/amd64` always (Fargate is x86_64) |
| migrate `P1013 invalid port number` | RDS password has special chars | `urlencode(local.rds_master_password)` in secrets.tf |
| apply: OIDC provider "already exists" | account already has the GitHub OIDC provider | use `data "aws_iam_openid_connect_provider"`, don't create one |
| task starts but ALB health check fails / server bound to wrong host | Next standalone binds `$HOSTNAME` | `export HOSTNAME=0.0.0.0` in entrypoint before `node server.js` |
| shared-mode app can't reach RDS | RDS SG doesn't trust the task SG | task wears `platform-ecs-egress` (which RDS trusts); confirm the provided SG is attached to the task ENI, else widen RDS ingress |
| `/api/health` returns 307 | auth middleware gating it | exclude `/api/health` from the matcher |
| migrate/seed not running on deploy | standalone image omits Prisma CLI | overlay full `node_modules` + copy `prisma/`, `prisma.config.ts`, `src/generated` (Dockerfile does this) |
| CI pushes a new image but the running task doesn't change | Express pins the image to a digest (versionConsistency) | roll via the deploy **action** / `update-express-gateway-service` (sets the new image); a bare ECS `update-service --force-new-deployment` re-runs the SAME digest |
| infra role changes don't take | `infrastructure_role_arn` is **immutable after create** | get it right on first create; to change, recreate the service |
| branded domain serves a 404 / wrong host from the ALB | CloudFront forwarded the viewer Host header | use the managed **AllViewerExceptHostHeader** origin-request policy so CloudFront sends the `*.on.aws` Host the ALB routes on (domain.tf does this) |
| login/forms 500 with "Invalid Server Actions request" / `x-forwarded-host ... does not match origin` | CloudFront sends the `*.on.aws` host, so Next's Server Actions CSRF check sees host≠Origin | add the branded domain to `experimental.serverActions.allowedOrigins` in `next.config`, rebuild, redeploy |
| after login the browser lands on the raw `*.on.aws` host, or `callbackUrl=https://0.0.0.0:3000/` | Auth.js built redirect/callback URLs from the rewritten host / server bind instead of the branded domain | set `AUTH_URL=https://<project>.apps.snhcap.com` (ecs.tf already does); keep `AUTH_TRUST_HOST=true` |
| listener-rule edits on the Express ALB vanish | the Express ALB is a **shared black box**; Express can overwrite manual edits | never hand-edit it — front it with CloudFront (domain.tf) |
| CloudFront origin empty / `express_origin_host` null at apply | the Express URL isn't known until the service exists | two-phase apply: `-target` the service, then full apply; or set `express_origin_host` from `describe-express-gateway-service` |
| re-apply: service "already exists" | orphaned failed service not in state | `aws ecs delete-express-gateway-service --service-arn <arn>` (find it via `aws ecs list-services --cluster default`), then apply |
| custom domain cert stuck pending validation | validation CNAMEs missing, or GoDaddy NS delegation for apps.snhcap.com broken | check `dig NS apps.snhcap.com` returns the Route 53 name servers |
| Microsoft Defender "might not be safe" on app link | raw `*.on.aws` URL has no domain reputation | always share `<project>.apps.snhcap.com`; optionally have M365 admin allowlist `*.apps.snhcap.com` |
| Next 16: middleware deprecated | renamed | use `proxy.ts` (same level as `app/`) |
| `timeout while waiting for plugin to start` / terraform hangs forever (Apple Silicon) | x86_64 terraform+providers crashing Rosetta | use the darwin_arm64 terraform binary, then `rm -rf .terraform && terraform init -upgrade` per project |

---

## Cost & teardown
- **Shared mode:** marginal cost ≈ the always-on Fargate task (1 vCPU / 2 GB ≈
  ~$36/mo; drop to 512/1024 for light PoCs) + a share of the ALB (one ALB is
  shared across ≤25 Express services in the VPC). RDS is the platform's fixed cost,
  paid once for all projects. Tear down a project with `terraform destroy` in ITS
  `infra/terraform/` — this removes the service/ECR/secrets/CloudFront but **not**
  the project's database on the shared RDS (drop it manually with psql if the data
  should go too).
- **Dedicated mode:** own RDS ≈ $15–30/mo + the Fargate task; **no NAT** (saved vs
  App Runner). `terraform destroy` removes everything including the data.
- **NEVER run destroy in `~/Development/aws-platform/terraform`** unless the user
  explicitly wants the whole platform gone — every shared-mode project's database
  lives on it (RDS has deletion protection + final snapshot as backstops).
- Rotate any API keys placed in `terraform.tfvars` before real production use.

## Python backend (`/backend` FastAPI)
If the repo also has a `/backend` FastAPI service, deploy it as a SECOND ECS
Express service alongside the frontend one:
- Duplicate the `ecs.tf` resources with a `-backend` suffix (`<project>-backend`),
  `container_port = 8000`, `health_check_path = "/health"` (add the endpoint to
  FastAPI), and a Dockerfile running `uvicorn src.main:app --host 0.0.0.0 --port 8000`.
- Backend migrations: Alembic in the entrypoint (`alembic upgrade head`) before
  starting uvicorn; it reuses the same `DATABASE_URL` secret (use
  `postgresql+psycopg://` form for SQLAlchemy — add a second secret if needed).
- Point the frontend at it with a non-secret env var (e.g.
  `BACKEND_URL=https://<backend on.aws url>`), and add the second service to the
  GitHub workflow (second build + deploy-action step).

## Notes
- One AWS account hosts many projects: unique `project_name` each; dedicated mode
  also needs a unique VPC CIDR.
- Existing App Runner services (lbmc, csip, dice, …) keep running — migrating them
  to ECS Express is a separate, opt-in effort, not part of a normal deploy.
- Confirm with the user before the first `terraform apply` and before `terraform
  destroy` — these create/delete real billable infrastructure.
