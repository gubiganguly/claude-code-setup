###############################################################################
# secrets.tf — App-managed secrets.
#
# Four secrets are managed here:
#   1. AUTH_SECRET     — random 64-char key for Auth.js session signing.
#   2. DATABASE_URL    — Postgres URL (node-postgres / Prisma), built from the
#                        RDS-managed master user secret.
#   3. DIRECT_URL      — same value as DATABASE_URL (Prisma direct connection).
#   4. ANTHROPIC_API_KEY — from var.anthropic_api_key.
#
# The RDS master user secret itself is created by `rds.tf` via
# manage_master_user_password = true. We do NOT recreate it here — we just
# read its current value to compose the connection URLs.
###############################################################################

# ---------------------------------------------------------------------------
# AUTH_SECRET — Auth.js session signing key
# ---------------------------------------------------------------------------

resource "random_password" "auth_secret" {
  length  = 64
  special = false
  # hex-friendly subset
  override_special = ""
}

resource "aws_secretsmanager_secret" "auth_secret" {
  name        = "${var.project_name}/auth-secret"
  description = "Auth.js session signing key for the ${var.project_name} app"

  tags = {
    Name = "${var.project_name}-auth-secret"
  }
}

resource "aws_secretsmanager_secret_version" "auth_secret" {
  secret_id     = aws_secretsmanager_secret.auth_secret.id
  secret_string = random_password.auth_secret.result
}

# ---------------------------------------------------------------------------
# DATABASE_URL / DIRECT_URL — composed from RDS master user secret
# ---------------------------------------------------------------------------
#
# RDS stores a JSON blob like:
#   {"username":"csip_admin","password":"...."}
#
# We read it, parse the password, and build a standard Postgres URL for the
# node-postgres driver that Prisma uses. Note: plain `postgresql://` (NOT
# `+asyncpg`). `sslmode=no-verify` tells the pg driver to use SSL without
# bundling the RDS CA bundle. If RDS rotates the password, re-running
# `terraform apply` refreshes both secrets (Terraform diffs the decoded value).

data "aws_secretsmanager_secret_version" "rds_master" {
  secret_id  = aws_db_instance.main.master_user_secret[0].secret_arn
  depends_on = [aws_db_instance.main]
}

locals {
  rds_master_password = jsondecode(data.aws_secretsmanager_secret_version.rds_master.secret_string)["password"]

  # urlencode the password — RDS-managed passwords can contain characters
  # (/, :, @, …) that corrupt the URL unless percent-encoded.
  database_url = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=no-verify",
    var.db_username,
    urlencode(local.rds_master_password),
    aws_db_instance.main.address,
    aws_db_instance.main.port,
    var.db_name,
  )

  # Prisma's direct connection. Same target — no PgBouncer in front of RDS.
  direct_url = local.database_url
}

resource "aws_secretsmanager_secret" "database_url" {
  name        = "${var.project_name}/database-url"
  description = "Postgres connection URL for ${var.project_name} (Prisma / node-postgres)"

  tags = {
    Name = "${var.project_name}-database-url"
  }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

resource "aws_secretsmanager_secret" "direct_url" {
  name        = "${var.project_name}/direct-url"
  description = "Prisma DIRECT_URL for ${var.project_name} (same target as DATABASE_URL)"

  tags = {
    Name = "${var.project_name}-direct-url"
  }
}

resource "aws_secretsmanager_secret_version" "direct_url" {
  secret_id     = aws_secretsmanager_secret.direct_url.id
  secret_string = local.direct_url
}

# ---------------------------------------------------------------------------
# ANTHROPIC_API_KEY — in-app AI features
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${var.project_name}/anthropic-api-key"
  description = "Anthropic API key for ${var.project_name} AI features"

  tags = {
    Name = "${var.project_name}-anthropic-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = var.anthropic_api_key
}
