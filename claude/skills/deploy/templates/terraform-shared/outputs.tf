output "app_url" {
  description = "Public HTTPS URL of the App Runner service."
  value       = "https://${aws_apprunner_service.app.service_url}"
}

output "ecr_repository_url" {
  description = "ECR repository URL — GitHub Actions pushes the git SHA and 'latest' tags here."
  value       = aws_ecr_repository.app.repository_url
}

output "github_actions_role_arn" {
  description = "Role ARN GitHub Actions assumes via OIDC. Set as the AWS_DEPLOY_ROLE_ARN repo variable."
  value       = aws_iam_role.github_actions.arn
}

output "db_endpoint" {
  description = "Shared platform RDS endpoint this project's database lives on."
  value       = "${data.aws_db_instance.platform.address}:${data.aws_db_instance.platform.port}"
}

output "db_name" {
  description = "This project's database on the shared instance."
  value       = local.db_name
}
