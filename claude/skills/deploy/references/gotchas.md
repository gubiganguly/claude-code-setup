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
