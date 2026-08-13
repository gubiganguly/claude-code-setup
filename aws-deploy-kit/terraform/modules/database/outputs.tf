output "database_url_secret_arn" {
  description = "ARN of the connection-string secret. Wire into the service as DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "database_name" {
  description = "Database created on the shared instance."
  value       = local.db_name
}

output "database_user" {
  description = "Least-privilege role the application connects as."
  value       = local.db_user
}

output "endpoint" {
  description = "host:port of the shared instance."
  value       = "${var.db_host}:${var.db_port}"
}

# Deliberately NOT output: the password, and the assembled connection string.
# Both would land in Terraform state as readable outputs. Consumers should
# reference database_url_secret_arn and let ECS inject the value at runtime.
