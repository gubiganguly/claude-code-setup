###############################################################################
# db.tf — This project's database + role on the SHARED platform RDS.
#
# The app never uses the platform master credentials: it connects as its own
# role (<project>_app) to its own database (<project>). Provisioning runs
# create-db.sh against the platform RDS public endpoint — your IP must be in
# the platform's admin_cidrs (it is unless your IP changed; if psql times out,
# update admin_cidrs in the platform stack and re-apply it).
###############################################################################

locals {
  # Postgres identifiers: underscores, not hyphens.
  db_name = replace(var.project_name, "-", "_")
  db_user = "${replace(var.project_name, "-", "_")}_app"
}

# special = false so the password is safe inside SQL quotes AND URL-safe
# (still urlencoded in secrets.tf for belt-and-braces).
resource "random_password" "db_user" {
  length  = 32
  special = false
}

resource "null_resource" "provision_db" {
  triggers = {
    db_name       = local.db_name
    db_user       = local.db_user
    password_hash = sha256(random_password.db_user.result)
  }

  provisioner "local-exec" {
    command = "${path.module}/create-db.sh"

    environment = {
      PLATFORM_HOST     = data.aws_db_instance.platform.address
      PLATFORM_PORT     = data.aws_db_instance.platform.port
      MASTER_SECRET_ARN = data.aws_db_instance.platform.master_user_secret[0].secret_arn
      PROJECT_DB        = local.db_name
      PROJECT_USER      = local.db_user
      PROJECT_PASSWORD  = random_password.db_user.result
      AWS_REGION        = var.aws_region
    }
  }
}
