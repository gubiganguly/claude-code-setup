###############################################################################
# secrets.tf — App-managed secrets (shared-platform mode).
#
# DATABASE_URL/DIRECT_URL point at THIS project's database on the shared RDS,
# authenticated as the project's own role (created in db.tf) — never the
# platform master user. Add/remove app secrets (API keys etc.) to match the
# app's .env.
###############################################################################

# ---------------------------------------------------------------------------
# AUTH_SECRET — Auth.js session signing key
# ---------------------------------------------------------------------------

resource "random_password" "auth_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "auth_secret" {
  name        = "${var.project_name}/auth-secret"
  description = "Auth.js session signing key for ${var.project_name}"

  tags = {
    Name = "${var.project_name}-auth-secret"
  }
}

resource "aws_secretsmanager_secret_version" "auth_secret" {
  secret_id     = aws_secretsmanager_secret.auth_secret.id
  secret_string = random_password.auth_secret.result
}

# ---------------------------------------------------------------------------
# DATABASE_URL / DIRECT_URL — project role @ shared RDS / project database
# ---------------------------------------------------------------------------

locals {
  database_url = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=no-verify",
    local.db_user,
    urlencode(random_password.db_user.result),
    data.aws_db_instance.platform.address,
    data.aws_db_instance.platform.port,
    local.db_name,
  )

  direct_url = local.database_url
}

resource "aws_secretsmanager_secret" "database_url" {
  name        = "${var.project_name}/database-url"
  description = "Postgres connection URL for ${var.project_name} (own db/role on shared platform RDS)"

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
# App secrets — one block per API key this app needs (example: Anthropic)
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${var.project_name}/anthropic-api-key"
  description = "Anthropic API key for ${var.project_name}"

  tags = {
    Name = "${var.project_name}-anthropic-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = var.anthropic_api_key
}
