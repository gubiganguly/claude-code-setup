# AWS Deployment Playbook — Full-stack app → App Runner (the easy way)

> **NOTE (2026-06-11):** this playbook describes DEDICATED mode (own VPC + RDS
> per project, ~$50/mo). Since then a shared platform exists — most projects
> should deploy in SHARED mode (~$5/mo) instead. See
> `~/Development/aws-platform/ARCHITECTURE.md` for the current architecture and
> use the `/deploy` skill, which knows both modes.

A reusable recipe for shipping a containerized full-stack web app (Next.js here,
but adaptable) to AWS so that:

- **First deploy = one `terraform apply`** (provisions all the infra).
- **Every deploy after = `git push`** (GitHub Actions builds the image and rolls
  the service; database migrations + seed run automatically on the container).

Based on the CSIP and LBMC deployments. Copy this file into each new project and
follow it. Replace `<project>` with a short slug (e.g. `csip`, `lbmc-quoting`).

---

## 1. The architecture you get

```
 laptop / GitHub ──docker build+push──▶ ECR (image)
                                          │ App Runner pulls :latest
                                          ▼
   Internet ──HTTPS──▶ AWS App Runner (runs the whole app container)
                                          │ private, via VPC connector
                                          ▼
                       RDS PostgreSQL (private subnets)
   Secrets Manager ──env──▶ App Runner   (DATABASE_URL, auth secret, API keys)
   GitHub OIDC role ──assumed by──▶ GitHub Actions (no static AWS keys)
```

Pieces (all created by Terraform): **VPC** (2 public + 2 private + 1 NAT),
**RDS Postgres** (private, RDS-managed master password in Secrets Manager),
**ECR** repo, **Secrets Manager** secrets, **App Runner** service + **VPC
connector**, **GitHub OIDC provider/role**, and a **GitHub Actions** deploy
workflow.

**Key idea — the container self-provisions.** On boot it runs
`migrate deploy` then idempotent seeds, so a fresh deploy comes up fully working
with data and **no manual database step**. This is what makes a private RDS
painless: the container reaches it through the VPC connector; you never have to
tunnel into the DB.

**Many projects, one AWS account.** Give each project a unique `project_name`
prefix and a unique VPC CIDR (`10.20.x` for one, `10.30.x` for the next, …) so
they coexist without colliding.

---

## 2. Files to add to the repo (copy these)

Easiest path: **copy the whole `infra/terraform/` folder, `Dockerfile`,
`docker-entrypoint.sh`, `.dockerignore`, and `.github/workflows/deploy.yml` from
a previous project (e.g. the `csip` repo)**, then change `project_name`, the VPC
CIDR, and the secret list. The templates below are the canonical, already-debugged
versions.

### 2a. `next.config.ts` — standalone output
```ts
const nextConfig = { output: "standalone" }
export default nextConfig
```

### 2b. Health endpoint — `src/app/api/health/route.ts`
```ts
export const dynamic = "force-dynamic"
export async function GET() {
  return Response.json({ status: "ok" })
}
```
If you use auth middleware, **exclude `/api/health` (and `/api/auth`) from it** so
the health check gets a clean 200, e.g. matcher
`['/((?!api/auth|api/health|login|_next/static|_next/image|favicon.ico|.*\\.).*)']`.

### 2c. `Dockerfile` (multi-stage, standalone + migration toolchain)
```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Prisma's schema engine wants OpenSSL; CA certs for TLS to RDS.
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY package.json package-lock.json ./
COPY prisma ./prisma          # so the postinstall `prisma generate` has the schema
RUN npm ci

FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build             # = prisma generate && next build (no DB needed)

FROM base AS runner
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN groupadd --system --gid 1001 nodejs && useradd --system --uid 1001 --gid nodejs nextjs
COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
# Overlay the FULL node_modules + Prisma CLI + schema + generated client so the
# container can run migrate + seed on boot (standalone trace alone omits these).
COPY --from=build --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=build --chown=nextjs:nodejs /app/prisma ./prisma
COPY --from=build --chown=nextjs:nodejs /app/prisma.config.ts ./prisma.config.ts
COPY --from=build --chown=nextjs:nodejs /app/tsconfig.json ./tsconfig.json
COPY --from=build --chown=nextjs:nodejs /app/src/generated ./src/generated
COPY --chown=nextjs:nodejs docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh
USER nextjs
EXPOSE 3000
CMD ["./docker-entrypoint.sh"]
```

### 2d. `docker-entrypoint.sh` (migrate + seed + bind fix)
```sh
#!/bin/sh
set -e
echo "[entrypoint] prisma migrate deploy…"
node node_modules/prisma/build/index.js migrate deploy   # idempotent, advisory-locked

echo "[entrypoint] seeding (idempotent)…"
if node node_modules/tsx/dist/cli.mjs prisma/seed.ts \
  && node node_modules/tsx/dist/cli.mjs prisma/seed-phase2.ts ; then
  echo "[entrypoint] seed complete"
else
  echo "[entrypoint] WARNING: seed failed — starting server anyway"
fi

# CRITICAL: App Runner overrides HOSTNAME with the instance hostname, and Next's
# standalone server binds to $HOSTNAME — which makes it unreachable and fails the
# health check. Force 0.0.0.0.
export HOSTNAME=0.0.0.0
export PORT="${PORT:-3000}"
exec node server.js
```
Make **every seed script idempotent** (guard: "if the base record already exists,
return"), because this runs on every boot.

### 2e. `.dockerignore`
```
node_modules
.next
.git
.env
.env.*
*.md
dev.db
.DS_Store
```

### 2f. `infra/terraform/` (copy from a prior project; per-file purpose)
`main.tf` (providers + region), `variables.tf`, `network.tf` (VPC/subnets/NAT/SGs),
`rds.tf` (Postgres, `manage_master_user_password = true`), `ecr.tf`, `secrets.tf`
(compose DATABASE_URL from the RDS-managed secret), `apprunner.tf` (service +
VPC connector + IAM), `oidc.tf` (GitHub OIDC role), `outputs.tf`,
`terraform.tfvars.example`, `.gitignore` (ignore `*.tfstate*`, `.terraform/`,
`terraform.tfvars`). See the gotchas in §5 for the three edits that matter.

### 2g. `.github/workflows/deploy.yml` (OIDC → build → ECR → App Runner)
```yaml
name: Deploy
on:
  push:
    branches: [main]
    paths: ["src/**","prisma/**","package.json","package-lock.json","Dockerfile","docker-entrypoint.sh","next.config.ts",".github/workflows/deploy.yml"]
  workflow_dispatch:
permissions: { id-token: write, contents: read }
concurrency: { group: deploy-main, cancel-in-progress: false }
env: { AWS_REGION: us-east-1, ECR_REPOSITORY: <project>, APP_RUNNER_SERVICE_NAME: <project> }
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with: { role-to-assume: "${{ vars.AWS_DEPLOY_ROLE_ARN }}", aws-region: "${{ env.AWS_REGION }}" }
      - id: ecr
        uses: aws-actions/amazon-ecr-login@v2
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64          # ubuntu runner is amd64 — fast, no emulation
          push: true
          tags: ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPOSITORY }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - run: |   # resolve service ARN, start deployment, poll until RUNNING
          ARN=$(aws apprunner list-services --query "ServiceSummaryList[?ServiceName=='${{ env.APP_RUNNER_SERVICE_NAME }}'].ServiceArn|[0]" --output text)
          aws apprunner start-deployment --service-arn "$ARN"
          for i in $(seq 1 30); do
            S=$(aws apprunner describe-service --service-arn "$ARN" --query Service.Status --output text)
            echo "status: $S"; [ "$S" = "RUNNING" ] && exit 0
            case "$S" in CREATE_FAILED|DELETE_FAILED|PAUSED) exit 1;; esac
            sleep 10
          done; exit 1
```

---

## 3. First-time deploy (one-time, ~20–25 min)

> Prereqs: AWS CLI logged into the target account (`aws sts get-caller-identity`),
> Docker running, Terraform ≥ 1.6.

```bash
# 1. Set required secrets in tfvars
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
#   edit: set project_name, github_owner/repo, any API keys (e.g. anthropic_api_key)
terraform init

# 2. Create the ECR repo FIRST (App Runner needs an image to exist before it starts)
terraform apply -target=aws_ecr_repository.app

# 3. Build + push the first image  (--platform linux/amd64 is MANDATORY)
cd ../..
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/<project>"
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com"
docker buildx build --platform linux/amd64 -t "$ECR:latest" --push .

# 4. Build the rest (VPC, RDS ~15 min, Secrets, OIDC, App Runner)
cd infra/terraform
terraform apply
#   note the outputs: app_url, github_actions_role_arn

# 5. Enable git-push deploys: in GitHub repo → Settings → Secrets and variables →
#    Actions → Variables → add AWS_DEPLOY_ROLE_ARN = <github_actions_role_arn output>

# 6. Open app_url — the container already migrated + seeded itself. Log in. Done.
```

## 4. Every deploy after
```bash
git add -A && git commit -m "…" && git push      # CI builds + deploys; migrations auto-apply
```

---

## 5. Gotchas that WILL bite you (the gold — fix these in the templates up front)

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | `terraform apply` fails creating App Runner: "no image" | App Runner needs the image at create time; ECR is empty | Create ECR first (`-target`) + push an image **before** the full apply |
| 2 | App Runner deploy fails; `exec format error` in logs | Image built for arm64 (Apple Silicon) | Always `docker buildx build --platform linux/amd64` |
| 3 | Migrate fails: `P1013 invalid port number in database URL` | RDS-managed password has special chars (`/ : @`) that corrupt the URL | **URL-encode the password**: `urlencode(local.rds_master_password)` in `secrets.tf` |
| 4 | `terraform apply` fails: OIDC `provider … already exists` | The account already has the GitHub OIDC provider (another project made it) | Use a **data source** (`data "aws_iam_openid_connect_provider"`), don't create a second |
| 5 | App Runner `CREATE_FAILED`, logs show server "Ready" but bound to `ip-…ec2.internal:3000` | App Runner overrides `HOSTNAME`; Next standalone binds to it → unreachable | **`export HOSTNAME=0.0.0.0`** in the entrypoint before starting the server |
| 6 | App can reach RDS but not the internet (external APIs fail) | VPC connector on **public** subnets (no public IP → no egress) | Put the VPC connector on **private** subnets (NAT route gives internet + RDS) |
| 7 | `/api/health` redirects (307) | auth middleware/proxy is gating it | Exclude `/api/health` (and `/api/auth`) from the middleware matcher |
| 8 | Health check fails during long boot | migrate + seed run before the server binds | Keep them fast (in-VPC is fast) and/or raise App Runner `unhealthy_threshold` (e.g. 10) |
| 9 | A killed `terraform apply` won't re-run: "state locked" | stale `.terraform.tfstate.lock.info` (local backend) | Delete the lock file (process is dead) or `terraform force-unlock <id>` |
| 10 | Re-apply collides: App Runner service "already exists" | a `CREATE_FAILED` service left orphaned, not in TF state | `aws apprunner delete-service --service-arn …`, then re-apply |
| 11 | Next 16: `middleware.ts` deprecated | renamed | use **`proxy.ts`** (same level as `app/`, i.e. `src/proxy.ts`) |
| 12 | Migrations don't run automatically | standalone image omits Prisma CLI | overlay full `node_modules` + copy `prisma/`, `prisma.config.ts`, `src/generated` (see Dockerfile) |

---

## 6. Cost & teardown
- Main cost drivers: **RDS** + the **NAT gateway** (~$32/mo each-ish) + App Runner
  compute. Rough order: low-tens of $/month for a light demo.
- Tear everything down: `cd infra/terraform && terraform destroy`.
- Rotate any API keys placed in `terraform.tfvars` before real production.

## 7. Quick checklist for a new project
- [ ] Copy `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `infra/terraform/`, `.github/workflows/deploy.yml`
- [ ] `next.config` → `output: "standalone"`; add `/api/health`; exclude it from middleware
- [ ] Set unique `project_name` + unique VPC CIDR (`10.X.0.0/16`)
- [ ] Make seed scripts idempotent
- [ ] AWS CLI → target account; `terraform init`
- [ ] ECR-first `-target` apply → build+push amd64 image → full `terraform apply`
- [ ] Set repo variable `AWS_DEPLOY_ROLE_ARN`
- [ ] Open `app_url`, verify login → then it's `git push` from here on
```
