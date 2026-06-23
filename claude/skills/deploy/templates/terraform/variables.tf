###############################################################################
# variables.tf — All input variables for the CSIP PoC
###############################################################################

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (prod, staging, dev). PoC is single-env = prod."
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Short project slug used as a prefix for resource names."
  type        = string
  default     = "csip"
}

# ---------------------------------------------------------------------------
# GitHub source — drives the OIDC trust policy for the deploy workflow
# ---------------------------------------------------------------------------

variable "github_owner" {
  description = "GitHub org/user that owns the repository."
  type        = string
  default     = "SNH-Capital"
}

variable "github_repo" {
  description = "GitHub repository name (no owner prefix)."
  type        = string
  default     = "csip"
}

variable "github_branch" {
  description = "Branch the OIDC role trusts (and the deploy workflow runs on)."
  type        = string
  default     = "main"
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

variable "db_name" {
  description = "Postgres database name created at first launch."
  type        = string
  default     = "csip"
}

variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "csip_admin"
}

variable "db_instance_class" {
  description = "RDS instance class. PoC default is the cheapest Graviton burst."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Initial allocated storage in GB."
  type        = number
  default     = 20
}

# ---------------------------------------------------------------------------
# App runtime sizing (Fargate task). Numeric CPU units / MiB of memory.
# Valid CPU: 256, 512, 1024, 2048, 4096. Memory must be valid for the CPU.
# The whole Next.js app runs here, so we give it a touch more headroom than a
# thin API would need.
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
# Application secrets
# ---------------------------------------------------------------------------

variable "anthropic_api_key" {
  description = <<-EOT
    REQUIRED. Anthropic API key used by the in-app AI features. Stored in
    Secrets Manager and injected into the ECS task as ANTHROPIC_API_KEY.
    Treat this value like a password — never commit it.
  EOT
  type        = string
  sensitive   = true
}
