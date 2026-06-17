variable "aws_region" {
  description = "AWS region (must match the shared platform)."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Short project slug — prefixes every resource, ECR repo, and the database name."
  type        = string
}

# ---------------------------------------------------------------------------
# Shared platform wiring
# ---------------------------------------------------------------------------

variable "platform_vpc_connector_arn" {
  description = <<-EOT
    ARN of the shared App Runner VPC connector ("platform-shared"). Get it with:
      aws apprunner list-vpc-connectors \
        --query "VpcConnectors[?VpcConnectorName=='platform-shared'].VpcConnectorArn" --output text
  EOT
  type        = string
}

# ---------------------------------------------------------------------------
# GitHub source — drives the OIDC trust policy for the deploy workflow
# ---------------------------------------------------------------------------

variable "github_owner" {
  description = "GitHub org/user that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (no owner prefix)."
  type        = string
}

variable "github_branch" {
  description = "Branch the OIDC role trusts."
  type        = string
  default     = "main"
}

# ---------------------------------------------------------------------------
# App runtime sizing (App Runner)
# ---------------------------------------------------------------------------

variable "app_cpu" {
  description = "App Runner CPU size (e.g. '0.25 vCPU', '0.5 vCPU', '1 vCPU')."
  type        = string
  default     = "1 vCPU"
}

variable "app_memory" {
  description = "App Runner memory size (e.g. '0.5 GB', '1 GB', '2 GB')."
  type        = string
  default     = "2 GB"
}

# ---------------------------------------------------------------------------
# Application secrets — replace/add to match THIS app's .env
# ---------------------------------------------------------------------------

variable "anthropic_api_key" {
  description = "Anthropic API key (example app secret — swap for whatever this app needs)."
  type        = string
  sensitive   = true
}
