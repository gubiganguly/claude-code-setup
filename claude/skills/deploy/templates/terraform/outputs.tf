###############################################################################
# outputs.tf — Everything the deploy workflow and the operator need printed
# after `terraform apply`.
#
# (db_secret_arn is defined in rds.tf, next to the resource it derives from.)
###############################################################################

output "app_url" {
  description = "Public HTTPS URL of the CSIP App Runner service (the whole app)."
  value       = "https://${aws_apprunner_service.app.service_url}"
}

output "ecr_repository_url" {
  description = "ECR repository URL — GitHub Actions pushes the git SHA and 'latest' tags here."
  value       = aws_ecr_repository.app.repository_url
}

output "github_actions_role_arn" {
  description = "Role ARN that GitHub Actions assumes via OIDC. Set as the AWS_DEPLOY_ROLE_ARN repo variable."
  value       = aws_iam_role.github_actions.arn
}

output "db_endpoint" {
  description = "RDS endpoint (hostname:port). Used by the app via the DATABASE_URL secret."
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
}

output "next_steps" {
  description = "Human-readable post-apply checklist."
  value       = <<-EOT

    ================================================================
    CSIP PoC — next steps
    ================================================================

    1. Push the app image. GitHub Actions (.github/workflows/deploy.yml)
       uses the OIDC role above to build, push to ECR, and trigger an
       App Runner deploy. Set the repo variable first (step 2). Or run a
       one-time manual push:

         aws ecr get-login-password --region ${var.aws_region} \
           | docker login --password-stdin --username AWS \
             ${aws_ecr_repository.app.repository_url}
         docker build --platform linux/amd64 \
           -t ${aws_ecr_repository.app.repository_url}:latest .
         docker push ${aws_ecr_repository.app.repository_url}:latest

    2. Set the repo variable so the deploy workflow can assume the role:
       Settings -> Secrets and variables -> Actions -> Variables tab:
         AWS_DEPLOY_ROLE_ARN = ${aws_iam_role.github_actions.arn}

    3. ONE-TIME schema + seed. RDS is private, so run this from a machine
       that can reach it (temporarily open the RDS SG / publicly_accessible
       to your IP, or use a bastion) with DATABASE_URL/DIRECT_URL pointed at
       the RDS endpoint — see infra/README.md for details:

         npx prisma migrate deploy
         npx tsx prisma/seed.ts && npx tsx prisma/seed-phase2.ts \
           && npx tsx prisma/seed-phase3.ts && npx tsx prisma/seed-demo-users.ts

       NOTE: migrations do NOT run automatically in the container. Re-run
       `prisma migrate deploy` the same way after future schema changes.

    4. Demo logins (created by the seeds above):
         gganguly@snhcap.com        / password123!
         mgram@snhcap.com           / password123!
         sarah.chen@acmesaas.com    / Password123!

    App URL: https://${aws_apprunner_service.app.service_url}
    ================================================================
  EOT
}
