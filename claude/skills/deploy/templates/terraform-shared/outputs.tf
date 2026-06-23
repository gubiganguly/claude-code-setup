# The branded HTTPS URL (https://<project>.apps.snhcap.com) is output as
# `custom_domain` by domain.tf — that's the URL to share. The outputs below are
# self-contained (no dependency on domain.tf, so it can be deleted cleanly).

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
  description = "Role ARN GitHub Actions assumes via OIDC. Set as the AWS_DEPLOY_ROLE_ARN repo variable."
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
  description = "Shared platform RDS endpoint this project's database lives on."
  value       = "${data.aws_db_instance.platform.address}:${data.aws_db_instance.platform.port}"
}

output "db_name" {
  description = "This project's database on the shared instance."
  value       = local.db_name
}
