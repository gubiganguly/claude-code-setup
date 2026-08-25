# Gotchas

Every one of these has cost someone real hours. Check here before debugging.

## Terraform and providers

| Symptom | Cause | Fix |
|---|---|---|
| `terraform init`: no `aws_ecs_express_gateway_service` | Provider too old | Pin `aws ~> 6.23`; the resource landed in 6.23.0 |
| "Blocks of type X are not expected here" on `network_configuration`, `scaling_target`, `aws_logs_configuration` | These are nested-object **attributes**, not blocks | Assignment syntax: `network_configuration = [{ ... }]` |
| `use_lockfile` rejected in the backend | Terraform older than 1.10 | Upgrade to 1.11+ |
| `timeout while waiting for plugin to start`, hangs forever on Apple Silicon | x86_64 Terraform crashing under Rosetta | Install the darwin_arm64 binary, then `rm -rf .terraform && terraform init -upgrade` |
| Changing an SG `description` forces replacement | `description` is ForceNew in the AWS provider | Leave it. If the SG is attached to RDS, replacing it bounces the database |
| Apply: OIDC provider "already exists" | Only one per account | Set `create_github_oidc_provider = false` in bootstrap |
| Disk fills up; `.terraform` directories are ~700 MB each | Every `terraform init` downloads its own private copy of the AWS provider | Configure the shared plugin cache (below). Measured: 16 projects held 15 GB of the same binaries |
| `plugin_cache_dir` is set but providers are still copied | **Terraform silently ignores the setting when the directory does not exist.** It will not create it | `mkdir -p ~/.terraform.d/plugin-cache`, then `rm -rf .terraform && terraform init` in each project |

## Local disk hygiene

Terraform and Docker both cache aggressively and neither ever cleans up. On one
machine this reached **127 GB**: 15 GB of duplicated Terraform providers and
112 GB of Docker build cache.

**Terraform: share one copy of each provider.** Create `~/.terraformrc`:

```hcl
plugin_cache_dir = "/Users/<you>/.terraform.d/plugin-cache"
```

Then **create the directory**, which is the step people miss:

```bash
mkdir -p ~/.terraform.d/plugin-cache
```

Existing projects keep their private copies until re-initialised. To reclaim:

```bash
find . -type d -name .terraform -prune -exec rm -rf {} +
terraform init            # providers are now symlinked into the cache
```

`.terraform/` is regenerable and holds no real state, so deleting it is safe.
Local state lives in `terraform.tfstate` **beside** it, never inside. Verify
before deleting anywhere unfamiliar.

**Docker: the build cache is usually the whole problem.**

```bash
docker system df          # look at the Build Cache row
docker builder prune -af  # clears it
```

Two traps in that output:

- The `RECLAIMABLE` column **understates build cache badly**. It counts only
  cache unused by a current build. A row reading "112.8 GB total, 17.29 GB
  reclaimable" freed the full 112.8 GB.
- `Docker.raw` is a sparse image that reports its ceiling, not its usage. Use
  `du -sh`, not `ls -lh`. It usually self-compacts within a minute of a prune;
  if it does not, rebuild it from Docker Desktop → Settings → Resources.

**Never run `docker system prune --volumes` without checking first.** Named
volumes hold local dev databases (`<project>_postgres-data` and similar).
On the audited machine all volumes totalled 311 MB with **0 B reclaimable**, so
the flag would have destroyed local Postgres data to free nothing.

```bash
docker volume ls          # look for named volumes before pruning anything
```

**Images:** ECR-backed tags are re-pullable and safe to delete. Locally-built
tags (`:test`, `:local`, `:lean`, anything with no registry prefix) may exist
nowhere else and may not be reproducible if their Dockerfile was never
committed. Delete the first group freely, the second only deliberately.

## Service will not start or stay healthy

| Symptom | Cause | Fix |
|---|---|---|
| `exec format error` | Image built for arm64 | `docker buildx build --platform linux/amd64` always |
| Task starts, ALB health check fails | Next standalone binds `$HOSTNAME`, which the runtime set to the container ID | `export HOSTNAME=0.0.0.0` before `node server.js` |
| `/api/health` returns 307 | Auth middleware gating it | Exclude `/api/health` and `/api/auth` from the matcher |
| App has no public URL, only internal | Tasks placed in **private** subnets, so Express made an internal ALB | Use public subnets. Express infers scheme from subnet type |
| Migration task cannot pull its image | Private subnets with no NAT and no VPC endpoints | Run it in public subnets with `assignPublicIp=ENABLED` |
| Provisioner fails pulling postgres | Docker Hub rate limit | Use the `public.ecr.aws` mirror (the default) |

## Database

| Symptom | Cause | Fix |
|---|---|---|
| `P1013 invalid port number` | Password has URL-special characters | `urlencode()` the password in the connection string |
| Provisioner times out connecting | Task SG not trusted by the RDS SG | Task must wear the platform egress SG that RDS admits on 5432 |
| `psql: could not connect` from a laptop | RDS is private, and correctly so | Use `scripts/psql.sh`, which runs psql inside the VPC |
| Migration succeeded but the app sees no tables | App connected to a different database than the migration | Both must use the same `DATABASE_URL` secret |
| Redeploy after destroy: "secret already scheduled for deletion" | Secrets Manager soft-delete window | Set `secret_recovery_window_days = 0` for throwaway projects, or `aws secretsmanager delete-secret --force-delete-without-recovery` |

## Domain and CloudFront

| Symptom | Cause | Fix |
|---|---|---|
| Branded domain 404s from the ALB | CloudFront forwarded the viewer Host header | Use the managed **AllViewerExceptHostHeader** origin-request policy so the ALB sees the `*.on.aws` host it routes on |
| "Invalid Server Actions request", `x-forwarded-host does not match origin` | Next's CSRF check sees host differing from Origin | Add the branded domain to `experimental.serverActions.allowedOrigins`, rebuild, redeploy |
| After login the browser lands on `*.on.aws`, or `callbackUrl=https://0.0.0.0:3000/` | Auth.js built URLs from the rewritten host or the bind address | Set `AUTH_URL` to the branded domain; keep `AUTH_TRUST_HOST=true` |
| Certificate stuck pending validation | Zone not delegated at the registrar | `dig NS <zone>` must return the Route 53 name servers |
| 504 on slow requests | CloudFront origin read timeout (default 30s) | Raise `origin_read_timeout` for LLM calls or slow server actions |
| Listener-rule edits on the Express ALB vanish | The Express ALB is a shared black box Express can overwrite | Never hand-edit it. Front it with CloudFront |
| Microsoft Defender flags the app link | Raw `*.on.aws` has no domain reputation | Share the branded domain; optionally allowlist `*.<zone>` in M365 |

## Deploys

| Symptom | Cause | Fix |
|---|---|---|
| CI pushes a new image, running task unchanged | Express pins the image to a digest | Deploy via the action or `update-express-gateway-service`. A bare `update-service --force-new-deployment` re-runs the SAME digest |
| Terraform reverts the image CI just deployed | Missing lifecycle rule | `ignore_changes = [primary_container[0].image]` |
| Infra role change has no effect | `infrastructure_role_arn` is **immutable after create** | Get it right first time; changing it means recreating the service |
| Re-apply: service "already exists" | Orphaned service not in state | `aws ecs delete-express-gateway-service --service-arn <arn>`, then apply |
| Two pushes race, older image wins | No concurrency control | The `concurrency` group in the workflow handles this. Keep it |
