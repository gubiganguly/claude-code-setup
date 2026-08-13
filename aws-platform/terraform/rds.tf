###############################################################################
# rds.tf — THE shared Postgres instance. One per account; every small project
# gets its own database + role on it (created at deploy time by the /deploy
# skill using the master credentials).
#
# Design decisions:
#   * Lives in the PUBLIC subnets with publicly_accessible = true, but the SG
#     only admits the ECS Express task egress SG and the operator's admin_cidrs.
#     This is what lets /deploy create databases and run migrations straight
#     from the laptop — no bastion. Inside the VPC the endpoint hostname still
#     resolves to the private IP, so app traffic never leaves the VPC.
#   * manage_master_user_password = true → master creds live in Secrets
#     Manager (AWS-rotated). Master is for ADMIN ONLY (create db/role);
#     apps connect as their own per-project role, so rotation never breaks them.
#   * This instance is load-bearing for every project on it:
#     deletion_protection = true, final snapshot on destroy, 7-day backups.
###############################################################################

resource "aws_db_subnet_group" "main" {
  name        = "platform-db-subnets"
  description = "Public subnets for the shared platform RDS (SG-restricted)"
  subnet_ids  = aws_subnet.public[*].id

  tags = {
    Name = "platform-db-subnets"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "platform-db"
  engine         = "postgres"
  engine_version = "17"

  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = 100 # storage autoscaling ceiling
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "platform"
  username = "platform_admin"

  manage_master_user_password = true

  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name
  publicly_accessible    = true
  multi_az               = false

  backup_retention_period   = 7
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "platform-db-final"
  apply_immediately         = true

  auto_minor_version_upgrade = true

  tags = {
    Name = "platform-db"
  }
}
