output "app_url" {
  description = "THE URL to share. The branded domain when one is configured, otherwise the raw Express URL."
  value       = local.public_url
}

output "express_url" {
  description = "AWS-provided *.on.aws URL. Useful for debugging; do not share it with customers."
  value       = module.service.express_url
}

output "has_custom_domain" {
  description = "Whether this deployment has a branded domain."
  value       = var.custom_domain != ""
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID, when a domain is configured."
  value       = var.custom_domain != "" ? module.domain[0].distribution_id : null
}

# --- Values to paste into GitHub Actions repo variables ---------------------

output "github_actions_variables" {
  description = "Set these three as Actions repository VARIABLES (not secrets)."
  value = {
    AWS_DEPLOY_ROLE_ARN        = module.cicd.role_arn
    AWS_ECS_EXECUTION_ROLE_ARN = module.service.execution_role_arn
    AWS_ECS_INFRA_ROLE_ARN     = module.service.infrastructure_role_arn
  }
}

output "gh_variable_commands" {
  description = "Copy-paste to configure the repo in one go."
  value = join("\n", [
    "gh variable set AWS_DEPLOY_ROLE_ARN --body '${module.cicd.role_arn}' --repo ${var.github_owner}/${var.github_repo}",
    "gh variable set AWS_ECS_EXECUTION_ROLE_ARN --body '${module.service.execution_role_arn}' --repo ${var.github_owner}/${var.github_repo}",
    "gh variable set AWS_ECS_INFRA_ROLE_ARN --body '${module.service.infrastructure_role_arn}' --repo ${var.github_owner}/${var.github_repo}",
  ])
}

# --- Operational ------------------------------------------------------------

output "service_arn" {
  description = "For aws ecs describe/update/delete-express-gateway-service."
  value       = module.service.service_arn
}

output "ecr_repository_url" {
  description = "Set as ECR_REPOSITORY in the CI workflow."
  value       = module.service.ecr_repository_url
}

output "log_group_name" {
  description = "Container logs: aws logs tail <this> --follow"
  value       = module.service.log_group_name
}

output "database_name" {
  description = "This project's database on the shared instance, null when enable_database is false."
  value       = var.enable_database ? module.database[0].database_name : null
}

output "task_role_arn" {
  description = "Attach runtime AWS permissions here if the app needs them."
  value       = module.service.task_role_arn
}
