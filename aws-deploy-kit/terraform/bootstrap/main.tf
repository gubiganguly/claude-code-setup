###############################################################################
# bootstrap/main.tf — Run ONCE per AWS account, before anything else.
#
# Creates the two things every later stack depends on but cannot create for
# itself:
#
#   1. An encrypted, versioned S3 bucket for Terraform state (with native S3
#      locking — no DynamoDB table needed since Terraform 1.10).
#   2. The GitHub OIDC identity provider, so CI never needs static AWS keys.
#
# THIS stack is the only one that uses local state, and that is deliberate: it
# has nowhere to put remote state until it has finished running. Its state
# describes two cheap, easily-recreated resources, and the bucket itself is
# protected by prevent_destroy. Commit `bootstrap.tfstate` to a private repo or
# keep it with the account's break-glass material.
#
# Usage:
#   terraform init && terraform apply
#   terraform output -raw backend_config    # paste into every other stack
###############################################################################

terraform {
  # 1.10 introduced S3 native locking (use_lockfile); 1.11 made it stable and
  # deprecated the DynamoDB table. Requiring 1.11 keeps the backend simple.
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Account-scoped so the name is globally unique without the operator having
  # to invent one.
  state_bucket = coalesce(
    var.state_bucket_name,
    "${var.org_slug}-tfstate-${data.aws_caller_identity.current.account_id}"
  )
}

# ---------------------------------------------------------------------------
# KMS key for state encryption. State contains resource attributes that are
# sensitive even when the app's real secrets live in Secrets Manager, so this
# is not optional.
# ---------------------------------------------------------------------------

resource "aws_kms_key" "state" {
  description             = "Encrypts Terraform state for ${var.org_slug}"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${var.org_slug}-tfstate"
  }
}

resource "aws_kms_alias" "state" {
  name          = "alias/${var.org_slug}-tfstate"
  target_key_id = aws_kms_key.state.key_id
}

# ---------------------------------------------------------------------------
# State bucket
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket

  # Losing this bucket means losing the ability to manage every stack in the
  # account. Removing this block is a two-step, deliberate act.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = local.state_bucket
  }
}

# Versioning is what makes a corrupted or truncated state recoverable. It is
# the single most important setting here.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Refuse any request that isn't TLS. Cheap, and closes the most common finding
# in any account review.
data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}

# Old state versions are tiny but unbounded. Keep 90 days of history, which is
# far more than any realistic rollback window.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# GitHub OIDC provider — account-wide, created once.
#
# Many accounts already have one (it can only exist once per account). Set
# create_github_oidc_provider = false to reuse the existing one instead of
# failing with EntityAlreadyExists.
# ---------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # GitHub's OIDC endpoint uses a publicly-trusted CA and IAM no longer
  # validates this list, but the API still requires a non-empty value.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name = "github-actions-oidc"
  }
}

data "aws_iam_openid_connect_provider" "github_existing" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}
