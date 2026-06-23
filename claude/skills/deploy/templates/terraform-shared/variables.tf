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

variable "platform_public_subnet_ids" {
  description = <<-EOT
    The shared platform's PUBLIC subnet IDs (≥2, in ≥2 AZs). ECS Express tasks
    run here so Express provisions an internet-facing ALB. Get them with:
      cd ~/Development/aws-platform/terraform && terraform output -json public_subnet_ids
  EOT
  type        = list(string)
}

variable "platform_ecs_security_group_id" {
  description = <<-EOT
    The shared `platform-ecs-egress` security group ID. RDS (platform-rds-sg)
    trusts it, so Express tasks wearing this SG can reach the shared database.
    Get it with:
      cd ~/Development/aws-platform/terraform && terraform output -raw ecs_egress_sg_id
    (If absent, apply the one-time platform prereq described in the deploy skill.)
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
# App runtime sizing (Fargate task). Numeric CPU units / MiB of memory.
# Valid CPU: 256, 512, 1024, 2048, 4096. Memory must be valid for the CPU.
# ---------------------------------------------------------------------------

variable "app_cpu" {
  description = "Fargate task CPU units (e.g. '256', '512', '1024', '2048')."
  type        = string
  default     = "1024"
}

variable "app_memory" {
  description = "Fargate task memory in MiB (e.g. '512', '1024', '2048')."
  type        = string
  default     = "2048"
}

# ---------------------------------------------------------------------------
# Application secrets — replace/add to match THIS app's .env
# ---------------------------------------------------------------------------

variable "anthropic_api_key" {
  description = "Anthropic API key (example app secret — swap for whatever this app needs)."
  type        = string
  sensitive   = true
}
