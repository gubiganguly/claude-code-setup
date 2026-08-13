###############################################################################
# main.tf — Shared deployment platform for all small projects.
#
# ONE of these per AWS account. Provides the fixed-cost infrastructure that
# individual project deploys (via the /deploy skill, shared mode) plug into:
#
#   * VPC (10.10.0.0/16) with public/private subnets + single NAT gateway
#   * One RDS Postgres instance hosting a separate database per project
#   * One shared egress SG (platform-ecs-egress) that platform-db trusts
#
# Per-project resources (ECR repo, ECS Express service, secrets, OIDC role,
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
  # 1.10 introduced native S3 state locking (use_lockfile), which the backend
  # block below relies on.
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state. Migrated from a local terraform.tfstate on 2026-08-13.
  # This state describes the VPC and the RDS instance that every project's
  # database lives on, so losing it would mean losing the ability to manage
  # any of them. Versioned + KMS-encrypted, with locking to stop two
  # concurrent applies corrupting it.
  backend "s3" {
    bucket       = "snh-tfstate-346698404534"
    key          = "platform/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "arn:aws:kms:us-east-1:346698404534:key/a55890ab-75e6-4f3a-8262-ffadd5eed915"
    use_lockfile = true
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
