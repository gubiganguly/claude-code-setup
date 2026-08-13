output "vpc_id" {
  description = "Shared VPC."
  value       = aws_vpc.main.id
}

output "vpc_name" {
  description = "Name tag projects use to discover the VPC."
  value       = "${var.platform_name}-vpc"
}

output "public_subnet_ids" {
  description = "Where application tasks run. Tagged Tier=public."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Where the database lives. No internet route. Tagged Tier=private."
  value       = aws_subnet.private[*].id
}

output "ecs_egress_sg_id" {
  description = "SG every project's tasks wear; trusted by the database."
  value       = aws_security_group.ecs_egress.id
}

output "ecs_egress_sg_name" {
  description = "Name tag projects use to discover the SG."
  value       = "${var.platform_name}-ecs-egress"
}

output "cluster_name" {
  description = "Shared ECS cluster."
  value       = aws_ecs_cluster.main.name
}

output "db_identifier" {
  description = "Shared RDS identifier. Projects look it up by this."
  value       = aws_db_instance.main.identifier
}

output "db_endpoint" {
  description = "Private endpoint. Reachable only from inside the VPC."
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
}

output "db_master_secret_arn" {
  description = "AWS-managed master credential. Read only by the in-VPC provisioning task."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "hosted_zone_name" {
  description = "Zone for branded domains, empty when DNS was skipped."
  value       = var.hosted_zone_name
}

output "hosted_zone_id" {
  description = "Route 53 zone ID."
  value       = var.hosted_zone_name == "" ? null : aws_route53_zone.apps[0].zone_id
}

output "hosted_zone_name_servers" {
  description = "DELEGATE THESE AT YOUR REGISTRAR. Certificate validation hangs until you do."
  value       = var.hosted_zone_name == "" ? null : aws_route53_zone.apps[0].name_servers
}

# The config block the /deploy skill reads. Writing it out here means a new
# operator never has to hunt for these values.
output "deploy_config" {
  description = "Paste into the deploy config file (see kit README)."
  value       = <<-EOT
    AWS_REGION=${var.aws_region}
    PLATFORM_VPC_NAME=${var.platform_name}-vpc
    PLATFORM_EGRESS_SG_NAME=${var.platform_name}-ecs-egress
    PLATFORM_DB_IDENTIFIER=${aws_db_instance.main.identifier}
    ECS_CLUSTER_NAME=${aws_ecs_cluster.main.name}
    HOSTED_ZONE_NAME=${var.hosted_zone_name}
  EOT
}
