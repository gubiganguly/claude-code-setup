# Cost

Every number here is from a real account audit in August 2026, not a pricing
page estimate.

## What a project actually costs

| Piece | Monthly | Notes |
|---|---:|---|
| Fargate task, 512/1024 | ~$18 | Always-on, one task |
| Fargate task, 1024/2048 | ~$36 | The old default. Usually 4x more than needed |
| Public IPv4 per task | ~$3.65 | Unavoidable in public subnets, still cheaper than a NAT until roughly 9 tasks |
| ALB share | ~$16 | Shared across up to 25 Express services **in the same VPC** |
| Database on shared RDS | $0 | Marginal. The instance is already paid for |
| Dedicated RDS | ~$14 | Only when a project needs its own instance |
| CloudFront + ACM + Route 53 | <$1 | For typical internal-tool traffic |
| Secrets | $0.40 each | Consolidate related keys into one JSON secret |
| CloudWatch logs | ~$0.50/GB | 30-day retention is set by default |

**A typical shared-mode project: about $20/month.** Same project in dedicated
mode with its own VPC and RDS: about $50, because it gets its own ALB and its
own database.

## Sizing

Start at **512 CPU / 1024 MiB** and raise only on evidence.

An audit of twelve deployed services found **eleven averaging under 1% CPU**,
all running the old 1024/2048 default. Several averaged 0.02%. One sat at
exactly 0.00% with its own VPC, ALB, and database.

| Workload | CPU / memory |
|---|---|
| Mostly-static frontend, light API | 256 / 512 |
| Standard internal tool, dashboard, CRUD | **512 / 1024** (default) |
| Real user traffic, or server-side rendering under load | 1024 / 2048 |
| Heavy compute, large in-memory work | 1024+ / 4096+ |

1024 MiB is the practical floor for a Node server. Below that, Next.js can boot
and then fail health checks under GC pressure, which is hard to diagnose.

Check before raising:

```bash
aws cloudwatch get-metric-statistics --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=default Name=ServiceName,Value=<svc> \
  --start-time "$(date -u -v-7d '+%Y-%m-%dT%H:%M:%SZ')" \
  --end-time "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --period 604800 --statistics Average Maximum
```

Sustained average above ~50% justifies more CPU. Anything under 5% is oversized.

## Shared beats dedicated, almost always

Dedicated mode gives a project its own VPC and RDS. That means its own ALB
(~$16/mo, because ALB sharing only works within a VPC) and its own database
(~$14/mo), so roughly **$30/month before the app runs at all**.

Use dedicated only when:
- a compliance requirement demands network isolation, or
- the workload would genuinely disturb neighbours on the shared database

"It feels cleaner" is not a reason. In the audited account, three of four
project stacks were dedicated and none of them needed to be.

## Recurring waste to check for

- **Idle services.** A service at 0% CPU with no requests is pure cost. Retire
  it or accept that it is a paid demo.
- **Dead ALBs.** More than one or two internet-facing ALBs usually means
  projects are spread across VPCs unnecessarily.
- **Orphaned NAT gateways.** ~$32/mo each. The v2 platform has none by design.
  If one exists, find what still routes through it before deleting.
- **Tagged ECR images.** Expire them, not just untagged layers. One audited repo
  had 84 images because the policy only covered untagged.
- **No budget alert.** Set one. An account went from $44 to $644/month in three
  months with nobody notified, because the only budget was a $1 zero-spend
  alarm that had been firing and ignored since day one.

## Turning a project off

```bash
cd infra/terraform && terraform destroy
```

Shared mode: removes the service, ECR, secrets, and CloudFront. **The database
is not removed** because it lives on the shared instance. Drop it explicitly
with `scripts/psql.sh` if the data should go too.

Never run destroy in `terraform/platform`. Every project's data is there.
