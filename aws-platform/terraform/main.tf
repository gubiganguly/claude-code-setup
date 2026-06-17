###############################################################################
# main.tf — Shared deployment platform for all small projects.
#
# ONE of these per AWS account. Provides the fixed-cost infrastructure that
# individual project deploys (via the /deploy skill, shared mode) plug into:
#
#   * VPC (10.10.0.0/16) with public/private subnets + single NAT gateway
#   * One RDS Postgres instance hosting a separate database per project
#   * One shared App Runner VPC connector (reused by every project's service)
#
# Per-project resources (ECR repo, App Runner service, secrets, OIDC role,
# database + user on the shared instance) live in each project's own
# infra/terraform — NOT here.
#
# Fixed monthly cost: NAT (~$32) + RDS db.t4g.micro (~$13) ≈ $45 total,
# amortized across every project deployed on it.
#
# State: local backend. This directory is the source of truth — don't delete
# terraform.tfstate. Migrate to S3 if more than one operator ever needs it.
###############################################################################

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "platform"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
