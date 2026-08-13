output "service_arn" {
  description = "Pass to `aws ecs (describe|update|delete)-express-gateway-service --service-arn`."
  value       = aws_ecs_express_gateway_service.app.service_arn
}

output "service_name" {
  description = "ECS service name — set as ECS_SERVICE_NAME in the CI workflow."
  value       = aws_ecs_express_gateway_service.app.service_name
}

output "express_url" {
  description = "AWS-provided *.on.aws URL. Prefer the branded domain when one is configured."
  value       = try(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, "")
}

output "express_origin_host" {
  description = "Bare hostname of the Express endpoint, ready to use as a CloudFront origin."
  value = try(
    replace(
      replace(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, "https://", ""),
      "/", ""
    ),
    ""
  )
}

output "ecr_repository_url" {
  description = "ECR repo URL — set as ECR_REPOSITORY in the CI workflow."
  value       = aws_ecr_repository.app.repository_url
}

output "ecr_repository_name" {
  description = "ECR repo name."
  value       = aws_ecr_repository.app.name
}

output "ecr_repository_arn" {
  description = "ECR repo ARN — scopes the CI push policy to this repo alone."
  value       = aws_ecr_repository.app.arn
}

output "execution_role_arn" {
  description = "Set as the AWS_ECS_EXECUTION_ROLE_ARN repo variable."
  value       = aws_iam_role.execution.arn
}

output "infrastructure_role_arn" {
  description = "Set as the AWS_ECS_INFRA_ROLE_ARN repo variable. Immutable after service creation."
  value       = aws_iam_role.infrastructure.arn
}

output "task_role_arn" {
  description = "Role the running application assumes. Attach runtime AWS permissions here."
  value       = aws_iam_role.task.arn
}

output "log_group_name" {
  description = "CloudWatch log group for container output."
  value       = aws_cloudwatch_log_group.app.name
}
