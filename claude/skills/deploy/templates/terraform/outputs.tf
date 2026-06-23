###############################################################################
# outputs.tf — Everything the deploy workflow and the operator need printed
# after `terraform apply`.
#
# The branded HTTPS URL (https://<project>.apps.snhcap.com) is output as
# `custom_domain` by domain.tf — that's the URL to share. The outputs here are
# self-contained (no dependency on domain.tf, so it can be deleted cleanly).
# (db_secret_arn is defined in rds.tf, next to the resource it derives from.)
###############################################################################

output "express_service_url" {
  description = "Raw AWS-provided ECS Express URL (the CloudFront origin). Share the branded custom_domain, not this."
  value       = try(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, "")
}

output "service_arn" {
  description = "ECS Express service ARN — pass to aws ecs (describe|update|delete)-express-gateway-service --service-arn."
  value       = aws_ecs_express_gateway_service.app.service_arn
}

output "ecr_repository_url" {
  description = "ECR repository URL — GitHub Actions pushes the git SHA and 'latest' tags here."
  value       = aws_ecr_repository.app.repository_url
}

output "github_actions_role_arn" {
  description = "Role ARN that GitHub Actions assumes via OIDC. Set as the AWS_DEPLOY_ROLE_ARN repo variable."
  value       = aws_iam_role.github_actions.arn
}

output "execution_role_arn" {
  description = "ECS task execution role. Set as the AWS_ECS_EXECUTION_ROLE_ARN repo variable."
  value       = aws_iam_role.ecs_execution.arn
}

output "infra_role_arn" {
  description = "ECS Express infrastructure role. Set as the AWS_ECS_INFRA_ROLE_ARN repo variable."
  value       = aws_iam_role.ecs_infrastructure.arn
}

output "db_endpoint" {
  description = "RDS endpoint (hostname:port). Used by the app via the DATABASE_URL secret."
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
}

output "next_steps" {
  description = "Human-readable post-apply checklist."
  value       = <<-EOT

    ================================================================
    ${var.project_name} — next steps (ECS Express Mode)
    ================================================================

    1. Set the repo variables so the deploy workflow can assume the role
       and deploy the service (Settings -> Secrets and variables ->
       Actions -> Variables tab):
         AWS_DEPLOY_ROLE_ARN        = ${aws_iam_role.github_actions.arn}
         AWS_ECS_EXECUTION_ROLE_ARN = ${aws_iam_role.ecs_execution.arn}
         AWS_ECS_INFRA_ROLE_ARN     = ${aws_iam_role.ecs_infrastructure.arn}

    2. Push to the deploy branch. GitHub Actions builds the image, pushes
       to ECR, and rolls the ECS Express service (the official
       aws-actions/amazon-ecs-deploy-express-service action waits for the
       deployment to stabilize). Migrations + idempotent seeds run inside
       the container on boot (docker-entrypoint.sh).

    3. Branded URL (after CloudFront finishes deploying + the cert validates):
       see the `custom_domain` output → https://${var.project_name}.apps.snhcap.com

    Container logs: CloudWatch /ecs/${var.project_name}
    ================================================================
  EOT
}
