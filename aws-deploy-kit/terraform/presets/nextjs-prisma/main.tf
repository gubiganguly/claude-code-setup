###############################################################################
# presets/nextjs-prisma — copy this directory to <your-repo>/infra/terraform.
#
# A Next.js app with Prisma and Postgres, deployed onto the shared platform.
# It wires three generic modules together and adds only the Next-specific bits
# (port 3000, /api/health, Auth.js env vars).
#
# For any other stack, copy presets/generic instead and set the container
# contract yourself.
#
# WHAT YOU EDIT: terraform.tfvars, plus the `app_secrets` block below if the
# app needs API keys.
#
# TWO COMMANDS TO GO LIVE:
#   ../../scripts/bootstrap-image.sh <service_name>   # ECR + first image
#   terraform init && terraform apply                 # everything else
#
# There is no `-target` step. v1 needed one because the service could not be
# created without an image; bootstrap-image.sh removes that ordering problem.
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

  # Filled in from the bootstrap stack's `backend_config` output.
  # Change only `key`. Never use local state: it cannot be shared, cannot be
  # locked, and stores resource attributes in plaintext on one laptop.
  backend "s3" {
    bucket       = "REPLACE_ME-tfstate-000000000000"
    key          = "projects/REPLACE_ME/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.service_name
      Environment = var.environment
      ManagedBy   = "terraform"
      DeployKit   = "v2"
    }
  }
}

# CloudFront certs must be issued in us-east-1. Aliased so the domain module
# works even when the app itself runs in another region.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# ---------------------------------------------------------------------------
# Platform lookups — the shared VPC, subnets, SG, and RDS are owned by the
# platform stack and only ever read here.
# ---------------------------------------------------------------------------

data "aws_db_instance" "platform" {
  db_instance_identifier = var.platform_db_identifier
}

data "aws_vpc" "platform" {
  filter {
    name   = "tag:Name"
    values = [var.platform_vpc_name]
  }
}

data "aws_subnets" "platform_public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.platform.id]
  }
  filter {
    name   = "tag:Tier"
    values = ["public"]
  }
}

data "aws_security_group" "platform_egress" {
  filter {
    name   = "tag:Name"
    values = [var.platform_egress_sg_name]
  }
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.platform.id]
  }
}

# ---------------------------------------------------------------------------
# Database — created inside the VPC by a one-shot task. See modules/database.
# ---------------------------------------------------------------------------

module "database" {
  source = "../../modules/database"

  service_name      = var.service_name
  db_host           = data.aws_db_instance.platform.address
  db_port           = data.aws_db_instance.platform.port
  master_secret_arn = data.aws_db_instance.platform.master_user_secret[0].secret_arn

  cluster_name       = var.cluster_name
  subnet_ids         = data.aws_subnets.platform_public.ids
  security_group_ids = [data.aws_security_group.platform_egress.id]
  assign_public_ip   = true

  secret_recovery_window_days = var.secret_recovery_window_days
}

# ---------------------------------------------------------------------------
# App secrets
#
# Terraform creates the CONTAINER and, for values it generates itself, the
# version. Values you supply (API keys) are written out-of-band so they never
# enter Terraform state or a tfvars file on disk:
#
#   aws secretsmanager put-secret-value \
#     --secret-id <service>/anthropic-api-key --secret-string 'sk-...'
#
# ignore_changes keeps Terraform from reverting them on the next apply.
# ---------------------------------------------------------------------------

resource "random_password" "auth_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "auth_secret" {
  name                    = "${var.service_name}/auth-secret"
  description             = "Auth.js session signing key for ${var.service_name}"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "auth_secret" {
  secret_id     = aws_secretsmanager_secret.auth_secret.id
  secret_string = random_password.auth_secret.result
}

resource "aws_secretsmanager_secret" "app" {
  for_each = toset(var.app_secret_names)

  name                    = "${var.service_name}/${each.value}"
  description             = "${each.value} for ${var.service_name} (value set out-of-band)"
  recovery_window_in_days = var.secret_recovery_window_days
}

# Placeholder so the service can start before the real value is set. The
# ignore_changes is what makes out-of-band population stick.
resource "aws_secretsmanager_secret_version" "app" {
  for_each = aws_secretsmanager_secret.app

  secret_id     = each.value.id
  secret_string = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

locals {
  # The canonical public URL. Auth.js needs an absolute base or it builds
  # callbacks from the CloudFront-rewritten host and sends users to *.on.aws.
  # Falls back to the Express URL when the project has no custom domain.
  public_url = var.custom_domain != "" ? "https://${var.custom_domain}" : module.service.express_url

  app_secret_arns = {
    for name, secret in aws_secretsmanager_secret.app :
    upper(replace(name, "-", "_")) => secret.arn
  }
}

module "service" {
  source = "../../modules/app-service"

  service_name = var.service_name
  cluster_name = var.cluster_name

  # Next.js contract
  container_port    = 3000
  health_check_path = "/api/health"

  cpu    = var.cpu
  memory = var.memory

  min_tasks          = var.min_tasks
  max_tasks          = var.max_tasks
  log_retention_days = var.log_retention_days

  subnet_ids         = data.aws_subnets.platform_public.ids
  security_group_ids = [data.aws_security_group.platform_egress.id]

  environment = merge(
    {
      NODE_ENV        = "production"
      AWS_REGION      = var.aws_region
      AUTH_TRUST_HOST = "true"
      # Seeds are opt-in. v1 ran demo seeds on every production boot.
      RUN_SEEDS = var.run_seeds ? "true" : "false"
    },
    var.custom_domain != "" ? { AUTH_URL = "https://${var.custom_domain}" } : {},
    var.environment_variables,
  )

  secrets = merge(
    {
      DATABASE_URL = module.database.database_url_secret_arn
      DIRECT_URL   = module.database.database_url_secret_arn
      AUTH_SECRET  = aws_secretsmanager_secret.auth_secret.arn
    },
    local.app_secret_arns,
  )

  task_role_policy_json = var.task_role_policy_json

  depends_on = [
    module.database,
    aws_secretsmanager_secret_version.auth_secret,
  ]
}

# ---------------------------------------------------------------------------
# Domain — OPTIONAL. Set custom_domain = "" to skip it entirely and use the
# AWS-provided *.on.aws URL.
# ---------------------------------------------------------------------------

module "domain" {
  source = "../../modules/domain"
  count  = var.custom_domain != "" ? 1 : 0

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  service_name        = var.service_name
  domain_name         = var.custom_domain
  hosted_zone_name    = var.hosted_zone_name
  origin_host         = module.service.express_origin_host
  origin_read_timeout = var.origin_read_timeout
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC deploy role
# ---------------------------------------------------------------------------

module "cicd" {
  source = "../../modules/github-oidc"

  service_name            = var.service_name
  github_owner            = var.github_owner
  github_repo             = var.github_repo
  github_branch           = var.github_branch
  ecr_repository_arn      = module.service.ecr_repository_arn
  execution_role_arn      = module.service.execution_role_arn
  infrastructure_role_arn = module.service.infrastructure_role_arn
  task_role_arn           = module.service.task_role_arn
}
