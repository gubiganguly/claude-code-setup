###############################################################################
# presets/generic — copy this directory to <your-repo>/infra/terraform.
#
# ANY container that listens on a port and answers a health check: Python, Go,
# Rust, Java, Node, anything.
#
# You declare the container contract in terraform.tfvars:
#   container_port     the port the app listens on
#   health_check_path  a path returning 200 with no auth
#   enable_database    whether it needs Postgres at all
#
# For a Next.js + Prisma app use presets/nextjs-prisma instead; it sets those
# three and wires Auth.js for you.
#
# WHAT YOU EDIT: terraform.tfvars.
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
  count  = var.enable_database ? 1 : 0

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
  public_url = var.custom_domain != "" ? "https://${var.custom_domain}" : module.service.express_url

  app_secret_arns = {
    for name, secret in aws_secretsmanager_secret.app :
    upper(replace(name, "-", "_")) => secret.arn
  }

  # DATABASE_URL is injected only when this service has a database. An app that
  # talks to something else entirely just sets enable_database = false.
  db_secrets = var.enable_database ? {
    DATABASE_URL = module.database[0].database_url_secret_arn
  } : {}

  # PUBLIC_URL is a useful convention for frameworks needing an absolute base
  # URL. It can only be set when a custom domain is configured: with no domain
  # the URL is an attribute of the service itself, and feeding that back into
  # the service's own environment is a dependency cycle.
  #
  # If an app with no custom domain needs its own URL, read it at runtime from
  # the request headers rather than from an env var.
  base_env = merge(
    { AWS_REGION = var.aws_region },
    var.custom_domain != "" ? { PUBLIC_URL = "https://${var.custom_domain}" } : {},
    var.environment_variables,
  )
}

module "service" {
  source = "../../modules/app-service"

  service_name = var.service_name
  cluster_name = var.cluster_name

  # The container contract. This is what makes the preset generic: set these
  # to whatever your app actually does.
  container_port    = var.container_port
  health_check_path = var.health_check_path

  cpu    = var.cpu
  memory = var.memory

  min_tasks          = var.min_tasks
  max_tasks          = var.max_tasks
  log_retention_days = var.log_retention_days

  subnet_ids         = data.aws_subnets.platform_public.ids
  security_group_ids = [data.aws_security_group.platform_egress.id]

  environment = local.base_env
  secrets     = merge(local.db_secrets, local.app_secret_arns)

  task_role_policy_json = var.task_role_policy_json

  depends_on = [module.database]
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
