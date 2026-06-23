###############################################################################
# outputs.tf — Everything a project's shared-mode deploy needs from the
# platform. Read with: terraform output (from this directory), or look the
# resources up by name/tag.
###############################################################################

output "vpc_id" {
  description = "Shared platform VPC."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnets (App Runner VPC connector ENIs)."
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "Public subnets (NAT, RDS)."
  value       = aws_subnet.public[*].id
}

output "vpc_connector_arn" {
  description = "Shared App Runner VPC connector — pass to every project's App Runner service."
  value       = aws_apprunner_vpc_connector.shared.arn
}

output "app_runner_egress_sg_id" {
  description = "SG used by the shared VPC connector."
  value       = aws_security_group.app_runner_egress.id
}

output "ecs_egress_sg_id" {
  description = "Shared SG for ECS Express tasks — pass to each project's Express service (trusted by platform-rds-sg)."
  value       = aws_security_group.ecs_egress.id
}

output "rds_address" {
  description = "Shared RDS hostname."
  value       = aws_db_instance.main.address
}

output "rds_port" {
  description = "Shared RDS port."
  value       = aws_db_instance.main.port
}

output "rds_master_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials (admin use only)."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}
