###############################################################################
# rds.tf — Postgres 16 for the app.
#
# PoC notes:
#   * deletion_protection = false and skip_final_snapshot = true so we can
#     tear the PoC down quickly. Flip BOTH to true for a real prod stack.
#   * manage_master_user_password = true gives us automatic rotation and a
#     managed Secrets Manager secret. Read via data.aws_secretsmanager_secret_version
#     in secrets.tf to build DATABASE_URL.
###############################################################################

resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-db-subnets"
  description = "Private subnets for ${var.project_name} RDS"
  subnet_ids  = aws_subnet.private[*].id

  tags = {
    Name = "${var.project_name}-db-subnets"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "16.4"

  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username

  # RDS-managed master password, auto-rotated, stored in Secrets Manager.
  manage_master_user_password = true

  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 7
  # NOTE: PoC values — for real prod, set deletion_protection = true and
  # skip_final_snapshot = false.
  deletion_protection = false
  skip_final_snapshot = true
  apply_immediately   = true

  auto_minor_version_upgrade = true

  tags = {
    Name = "${var.project_name}-db"
  }
}

output "db_secret_arn" {
  description = "ARN of the RDS-managed master user secret (Secrets Manager)."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}
