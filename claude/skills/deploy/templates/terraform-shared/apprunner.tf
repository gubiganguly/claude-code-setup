###############################################################################
# apprunner.tf — This project's App Runner service (shared-platform mode).
#
# Identical to the dedicated-mode service except egress goes through the
# SHARED VPC connector (var.platform_vpc_connector_arn) — no per-project
# connector, subnets, or NAT.
###############################################################################

# ---------------------------------------------------------------------------
# IAM — access role (pulls from ECR) and instance role (runtime perms)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "apprunner_access_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_access" {
  name               = "${var.project_name}-apprunner-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_access_trust.json

  tags = {
    Name = "${var.project_name}-apprunner-access"
  }
}

resource "aws_iam_role_policy_attachment" "apprunner_access_ecr" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

data "aws_iam_policy_document" "apprunner_instance_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${var.project_name}-apprunner-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_instance_trust.json

  tags = {
    Name = "${var.project_name}-apprunner-instance"
  }
}

data "aws_iam_policy_document" "apprunner_instance_inline" {
  # Read ONLY this project's secrets — never the platform master secret.
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

resource "aws_iam_role_policy" "apprunner_instance" {
  name   = "${var.project_name}-apprunner-instance"
  role   = aws_iam_role.apprunner_instance.id
  policy = data.aws_iam_policy_document.apprunner_instance_inline.json
}

# ---------------------------------------------------------------------------
# App Runner service
# ---------------------------------------------------------------------------

resource "aws_apprunner_service" "app" {
  service_name = var.project_name

  source_configuration {
    auto_deployments_enabled = true

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.app.repository_url}:latest"
      image_repository_type = "ECR"

      image_configuration {
        port = "3000"

        runtime_environment_variables = {
          AUTH_TRUST_HOST = "true"
          NODE_ENV        = "production"
          AWS_REGION      = var.aws_region
        }

        runtime_environment_secrets = {
          DATABASE_URL      = aws_secretsmanager_secret.database_url.arn
          DIRECT_URL        = aws_secretsmanager_secret.direct_url.arn
          AUTH_SECRET       = aws_secretsmanager_secret.auth_secret.arn
          ANTHROPIC_API_KEY = aws_secretsmanager_secret.anthropic_api_key.arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.app_cpu
    memory            = var.app_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = var.platform_vpc_connector_arn
    }

    ingress_configuration {
      is_publicly_accessible = true
    }
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/api/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    # Generous so boot-time migrate + seed don't trip the health check.
    unhealthy_threshold = 10
  }

  tags = {
    Name = var.project_name
  }

  depends_on = [
    aws_iam_role_policy.apprunner_instance,
    aws_iam_role_policy_attachment.apprunner_access_ecr,
    aws_secretsmanager_secret_version.auth_secret,
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.direct_url,
    aws_secretsmanager_secret_version.anthropic_api_key,
    null_resource.provision_db,
  ]
}
