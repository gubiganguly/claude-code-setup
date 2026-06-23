###############################################################################
# main.tf — Terraform + provider setup for the CSIP PoC
#
# This is a single full-stack Next.js app — server actions, Prisma, auth, and
# AI all run inside the Next.js server. There is ONE ECS Express Mode service
# running the whole container (no Amplify, no separate backend, no S3).
#
# State backend:
#   For the PoC we use the default LOCAL backend (terraform.tfstate sits in this
#   directory). This is acceptable while only one person operates the stack.
#
#   To collaborate or harden later, uncomment the S3 backend block below, create
#   the bucket + DynamoDB lock table manually (or via a tiny bootstrap module),
#   then run `terraform init -migrate-state`.
#
#   terraform {
#     backend "s3" {
#       bucket         = "csip-tfstate-<account-id>"
#       key            = "infra/terraform.tfstate"
#       region         = "us-east-1"
#       dynamodb_table = "csip-tflock"
#       encrypt        = true
#     }
#   }
###############################################################################

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # aws_ecs_express_gateway_service landed in provider v6.23.0.
      version = "~> 6.23"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "csip"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

# Handy data sources used across the stack
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}
