output "role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub Actions."
  value       = aws_iam_role.github_actions.arn
}

output "role_name" {
  description = "Role name."
  value       = aws_iam_role.github_actions.name
}
