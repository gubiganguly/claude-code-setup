###############################################################################
# ecs.tf — The app on Amazon ECS Express Mode (dedicated-VPC mode).
#
# One `aws_ecs_express_gateway_service` stands up the whole production stack:
# a Fargate task, an internet-facing Application Load Balancer with an HTTPS
# listener + ACM cert, target group, security groups, auto-scaling, and an
# AWS-provided `*.on.aws` URL. We front that URL with CloudFront for the
# branded domain (see domain.tf).
#
# Networking: tasks run in this stack's PUBLIC subnets (Express → internet-
# facing ALB; tasks egress via the IGW). They reach RDS in the private subnets
# over the in-VPC route, gated by the RDS SG which trusts aws_security_group.ecs_tasks.
###############################################################################

# ---------------------------------------------------------------------------
# IAM — execution role (pulls images, reads secrets for injection, writes logs)
# and infrastructure role (lets Express manage the ALB/SGs/scaling on our behalf)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_execution_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${var.project_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_trust.json

  tags = {
    Name = "${var.project_name}-ecs-execution"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The execution role reads this app's secrets at task launch to inject them as
# container env (the `secret {}` blocks below).
data "aws_iam_policy_document" "ecs_execution_secrets" {
  statement {
    sid    = "ReadSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      aws_secretsmanager_secret.auth_secret.arn,
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.direct_url.arn,
      aws_secretsmanager_secret.anthropic_api_key.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name   = "${var.project_name}-ecs-execution-secrets"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_secrets.json
}

data "aws_iam_policy_document" "ecs_infrastructure_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_infrastructure" {
  name               = "${var.project_name}-ecs-infrastructure"
  assume_role_policy = data.aws_iam_policy_document.ecs_infrastructure_trust.json

  tags = {
    Name = "${var.project_name}-ecs-infrastructure"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_infrastructure_managed" {
  role       = aws_iam_role.ecs_infrastructure.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

# ---------------------------------------------------------------------------
# CloudWatch log group for the service container.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 30

  tags = {
    Name = "${var.project_name}-logs"
  }
}

# ---------------------------------------------------------------------------
# ECS Express Mode service
# ---------------------------------------------------------------------------

resource "aws_ecs_express_gateway_service" "app" {
  service_name            = var.project_name
  cluster                 = "default"
  execution_role_arn      = aws_iam_role.ecs_execution.arn
  infrastructure_role_arn = aws_iam_role.ecs_infrastructure.arn

  cpu               = var.app_cpu
  memory            = var.app_memory
  health_check_path = "/api/health"

  primary_container {
    image          = "${aws_ecr_repository.app.repository_url}:latest"
    container_port = 3000

    aws_logs_configuration = [{
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "ecs"
    }]

    environment {
      name  = "AUTH_TRUST_HOST"
      value = "true"
    }
    # Pin the canonical public URL. Behind CloudFront the request host is the
    # *.on.aws origin, so Auth.js would otherwise build redirect/callback URLs
    # from the wrong host (or the 0.0.0.0:3000 bind). Remove if the app has no
    # auth/redirect logic that needs an absolute base URL.
    environment {
      name  = "AUTH_URL"
      value = "https://${var.project_name}.apps.snhcap.com"
    }
    environment {
      name  = "NODE_ENV"
      value = "production"
    }
    environment {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    secret {
      name       = "DATABASE_URL"
      value_from = aws_secretsmanager_secret.database_url.arn
    }
    secret {
      name       = "DIRECT_URL"
      value_from = aws_secretsmanager_secret.direct_url.arn
    }
    secret {
      name       = "AUTH_SECRET"
      value_from = aws_secretsmanager_secret.auth_secret.arn
    }
    secret {
      name       = "ANTHROPIC_API_KEY"
      value_from = aws_secretsmanager_secret.anthropic_api_key.arn
    }
  }

  # PUBLIC subnets → internet-facing ALB + IGW egress. Private subnets would
  # give an INTERNAL ALB (no public URL), so always use public here.
  network_configuration = [{
    subnets         = aws_subnet.public[*].id
    security_groups = [aws_security_group.ecs_tasks.id]
  }]

  scaling_target = [{
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 60
    min_task_count            = 1
    max_task_count            = 10
  }]

  # CI (the deploy workflow) owns the rolling image tag — Terraform sets the
  # initial `:latest` and then ignores image drift so the two don't fight.
  lifecycle {
    ignore_changes = [primary_container[0].image]
  }

  tags = {
    Name = var.project_name
  }

  depends_on = [
    aws_iam_role_policy.ecs_execution_secrets,
    aws_iam_role_policy_attachment.ecs_execution_managed,
    aws_iam_role_policy_attachment.ecs_infrastructure_managed,
    aws_secretsmanager_secret_version.auth_secret,
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.direct_url,
    aws_secretsmanager_secret_version.anthropic_api_key,
  ]
}
