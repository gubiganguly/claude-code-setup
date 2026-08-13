###############################################################################
# modules/database — a database + least-privilege role on a SHARED RDS,
# provisioned from INSIDE the VPC.
#
# WHY THIS EXISTS
# v1 created the database by running psql from the operator's laptop through a
# `local-exec` provisioner. That forced three bad things:
#   * RDS had to be publicly_accessible
#   * the operator's current IP had to be in the DB security group
#   * the first deploy could never run in CI
#
# Here the psql runs in a one-shot Fargate task on the VPC's own subnets. The
# only thing the caller needs is IAM permission to RunTask, so it works
# identically from a laptop, from CI, or from a different operator's machine,
# and the RDS instance can stay private.
#
# Idempotent: creating an existing database or role is a no-op, and the role's
# password is reset on every run so rotation just works.
###############################################################################

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  # Postgres identifiers want underscores, not hyphens.
  db_name = replace(var.service_name, "-", "_")
  db_user = "${replace(var.service_name, "-", "_")}_app"
}

# special = false keeps the password safe inside SQL literals AND inside a URL.
# It is still urlencoded downstream as a second line of defence.
resource "random_password" "db" {
  length  = 32
  special = false
}

# ---------------------------------------------------------------------------
# The provisioning task
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "provisioner" {
  name              = "/ecs/${var.service_name}-db-provisioner"
  retention_in_days = 14
  tags              = { Name = "${var.service_name}-db-provisioner" }
}

data "aws_iam_policy_document" "task_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "provisioner" {
  name               = "${var.service_name}-db-provisioner"
  assume_role_policy = data.aws_iam_policy_document.task_trust.json
  tags               = { Name = "${var.service_name}-db-provisioner" }
}

resource "aws_iam_role_policy_attachment" "provisioner_managed" {
  role       = aws_iam_role.provisioner.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The provisioner is the ONLY thing that ever reads the RDS master credential.
# The application itself never sees it.
data "aws_iam_policy_document" "provisioner_secrets" {
  statement {
    sid       = "ReadMasterSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.master_secret_arn]
  }
}

resource "aws_iam_role_policy" "provisioner_secrets" {
  name   = "${var.service_name}-db-provisioner-secrets"
  role   = aws_iam_role.provisioner.id
  policy = data.aws_iam_policy_document.provisioner_secrets.json
}

resource "aws_ecs_task_definition" "provisioner" {
  family                   = "${var.service_name}-db-provisioner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.provisioner.arn

  container_definitions = jsonencode([
    {
      name      = "provisioner"
      image     = var.provisioner_image
      essential = true

      # ECS can pull a single key out of a JSON secret with the ":key::"
      # suffix, so we never have to parse JSON in the shell.
      secrets = [
        { name = "PGUSER", valueFrom = "${var.master_secret_arn}:username::" },
        { name = "PGPASSWORD", valueFrom = "${var.master_secret_arn}:password::" },
      ]

      environment = [
        { name = "PGHOST", value = var.db_host },
        { name = "PGPORT", value = tostring(var.db_port) },
        { name = "PGDATABASE", value = var.master_database },
        { name = "PGSSLMODE", value = "require" },
        { name = "TARGET_DB", value = local.db_name },
        { name = "TARGET_USER", value = local.db_user },
        { name = "TARGET_PASSWORD", value = random_password.db.result },
      ]

      command = ["sh", "-c", file("${path.module}/provision.sh")]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.provisioner.name
          "awslogs-region"        = data.aws_region.current.region
          "awslogs-stream-prefix" = "provision"
        }
      }
    }
  ])

  tags = { Name = "${var.service_name}-db-provisioner" }
}

# ---------------------------------------------------------------------------
# Run it.
#
# local-exec here only calls the AWS API (RunTask + wait), so unlike v1 it
# needs no network path to the database and no IP allowlisting. It re-runs
# whenever the database name, role name, or password changes.
# ---------------------------------------------------------------------------

resource "null_resource" "provision" {
  triggers = {
    db_name       = local.db_name
    db_user       = local.db_user
    password_hash = sha256(random_password.db.result)
    task_def      = aws_ecs_task_definition.provisioner.arn
  }

  provisioner "local-exec" {
    interpreter = ["/bin/sh", "-c"]
    command     = file("${path.module}/run-provisioner.sh")

    environment = {
      CLUSTER          = var.cluster_name
      TASK_DEFINITION  = aws_ecs_task_definition.provisioner.arn
      SUBNET_IDS       = join(",", var.subnet_ids)
      SECURITY_GROUPS  = join(",", var.security_group_ids)
      AWS_REGION       = data.aws_region.current.region
      ASSIGN_PUBLIC_IP = var.assign_public_ip ? "ENABLED" : "DISABLED"
      LOG_GROUP        = aws_cloudwatch_log_group.provisioner.name
    }
  }

  depends_on = [
    aws_iam_role_policy.provisioner_secrets,
    aws_iam_role_policy_attachment.provisioner_managed,
    aws_cloudwatch_log_group.provisioner,
  ]
}

# ---------------------------------------------------------------------------
# Connection string secret
#
# Built here (not by the caller) so the plaintext password never has to be
# passed between modules or surfaced as an output.
# ---------------------------------------------------------------------------

locals {
  database_url = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=%s",
    local.db_user,
    urlencode(random_password.db.result),
    var.db_host,
    var.db_port,
    local.db_name,
    var.sslmode,
  )
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.service_name}/database-url"
  description             = "Postgres URL for ${var.service_name} (own database + role on the shared instance)"
  recovery_window_in_days = var.secret_recovery_window_days
  tags                    = { Name = "${var.service_name}-database-url" }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}
