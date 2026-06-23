###############################################################################
# main.tf — Project deploy in SHARED-PLATFORM mode.
#
# This stack creates only the PER-PROJECT pieces: ECR repo, ECS Express Mode
# service (+ its IAM roles), app secrets, GitHub OIDC role, ACM/CloudFront for
# the domain, and a database + role on the shared platform RDS. The VPC, public
# subnets, IGW, RDS instance, and shared ECS task SG are owned by the platform
# stack (~/Development/aws-platform/terraform) and referenced here, never created.
#
# State: local backend (terraform.tfstate in this directory).
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
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# ---------------------------------------------------------------------------
# Shared platform lookups
# ---------------------------------------------------------------------------

# The shared RDS instance — gives us the endpoint and the master secret ARN
# (used only to provision this project's database + role).
data "aws_db_instance" "platform" {
  db_instance_identifier = "platform-db"
}
