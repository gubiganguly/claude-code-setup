###############################################################################
# modules/app-service — THE GENERIC CORE.
#
# Takes any container that listens on a port and answers a health check, and
# runs it on ECS Express Mode with an ECR repo, IAM roles, logs, autoscaling,
# and a GitHub Actions OIDC deploy role.
#
# Deliberately knows NOTHING about Next.js, Prisma, Node, or Postgres. Anything
# framework-specific belongs in a preset (see terraform/presets/) or is passed
# in through `environment` / `secrets`.
#
# Networking: tasks run in PUBLIC subnets. Express derives ALB scheme from
# subnet type — private subnets produce an INTERNAL ALB with no public URL, and
# also drag in a NAT gateway. Public subnets + a no-ingress SG is both cheaper
# and simpler; the task is reachable only through the ALB either way.
###############################################################################

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }
}

data "aws_partition" "current" {}

locals {
  # Secrets arrive as {ENV_NAME = secret_arn}. The execution role must be able
  # to read exactly these and nothing else.
  secret_arns = values(var.secrets)
}

# ---------------------------------------------------------------------------
# ECR repository
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = var.service_name
  image_tag_mutability = "MUTABLE" # CI moves the `latest` tag

  image_scanning_configuration {
    scan_on_push = true
  }

  # Images are rebuilt from git on demand, so force_delete keeps teardown from
  # blocking on leftover tags.
  force_delete = true

  tags = {
    Name = var.service_name
  }
}

# v1 expired only UNTAGGED images, so every SHA-tagged build accumulated
# forever. Expire old tagged builds too, keeping enough to roll back.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the ${var.ecr_keep_tagged_images} most recent SHA-tagged images (rollback window)"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = var.ecr_keep_tagged_images
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged layers after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# IAM — execution role (pull image, read secrets, write logs)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "execution_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.service_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.execution_trust.json
  tags               = { Name = "${var.service_name}-ecs-execution" }
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Scoped to exactly the secrets this service injects. Skipped entirely when the
# service has none, so we never attach an empty-resource policy.
data "aws_iam_policy_document" "execution_secrets" {
  count = length(local.secret_arns) > 0 ? 1 : 0

  statement {
    sid       = "ReadOwnSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = local.secret_arns
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count  = length(local.secret_arns) > 0 ? 1 : 0
  name   = "${var.service_name}-execution-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets[0].json
}

# ---------------------------------------------------------------------------
# IAM — task role (what the APPLICATION itself may call at runtime)
#
# v1 had no task role at all, so an app needing S3 or Bedrock had nowhere to
# put those grants. Always created; empty unless the caller passes policies.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "task" {
  name               = "${var.service_name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.execution_trust.json
  tags               = { Name = "${var.service_name}-ecs-task" }
}

resource "aws_iam_role_policy" "task_inline" {
  count  = var.task_role_policy_json == null ? 0 : 1
  name   = "${var.service_name}-task-inline"
  role   = aws_iam_role.task.id
  policy = var.task_role_policy_json
}

# ---------------------------------------------------------------------------
# IAM — infrastructure role (lets Express manage the ALB/SG/scaling for us)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "infrastructure_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "infrastructure" {
  name               = "${var.service_name}-ecs-infrastructure"
  assume_role_policy = data.aws_iam_policy_document.infrastructure_trust.json
  tags               = { Name = "${var.service_name}-ecs-infrastructure" }
}

resource "aws_iam_role_policy_attachment" "infrastructure_managed" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.service_name}"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.service_name}-logs" }
}

# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

resource "aws_ecs_express_gateway_service" "app" {
  service_name            = var.service_name
  cluster                 = var.cluster_name
  execution_role_arn      = aws_iam_role.execution.arn
  task_role_arn           = aws_iam_role.task.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn

  cpu               = var.cpu
  memory            = var.memory
  health_check_path = var.health_check_path

  primary_container {
    image          = "${aws_ecr_repository.app.repository_url}:${var.initial_image_tag}"
    container_port = var.container_port

    aws_logs_configuration = [{
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "ecs"
    }]

    dynamic "environment" {
      for_each = var.environment
      content {
        name  = environment.key
        value = environment.value
      }
    }

    dynamic "secret" {
      for_each = var.secrets
      content {
        name       = secret.key
        value_from = secret.value
      }
    }
  }

  network_configuration = [{
    subnets         = var.subnet_ids
    security_groups = var.security_group_ids
  }]

  scaling_target = [{
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = var.scaling_cpu_target
    min_task_count            = var.min_tasks
    max_task_count            = var.max_tasks
  }]

  # CI owns the rolling image tag. Terraform sets the initial one and then
  # stops caring, so `terraform apply` never reverts a deploy.
  lifecycle {
    ignore_changes = [primary_container[0].image]
  }

  tags = { Name = var.service_name }

  depends_on = [
    aws_iam_role_policy_attachment.execution_managed,
    aws_iam_role_policy_attachment.infrastructure_managed,
    aws_iam_role_policy.execution_secrets,
  ]
}
