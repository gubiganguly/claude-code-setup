###############################################################################
# variables.tf — everything a project sets lives here.
#
# Values that describe the ACCOUNT (region, platform names, hosted zone) come
# from the deploy config file, not from this repo. See scripts/load-config.sh
# and the kit README. Nothing here hardcodes an organisation, account ID, or
# domain.
###############################################################################

# --- Identity ---------------------------------------------------------------

variable "service_name" {
  description = "Short slug for the project. Names the ECR repo, ECS service, database, and IAM roles."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}$", var.service_name))
    error_message = "service_name must be 2-31 chars, lowercase alphanumeric or hyphen."
  }
}

variable "environment" {
  description = "Environment label for tagging (prod, staging, dev)."
  type        = string
  default     = "prod"
}

# --- Container contract -----------------------------------------------------

variable "container_port" {
  description = "Port the container listens on. 3000 Node, 8000 FastAPI/Django, 8080 JVM/Go."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Path returning 200 WITHOUT authentication. The service never stabilises if this is gated."
  type        = string
  default     = "/health"
}

variable "enable_database" {
  description = <<-EOT
    Give this service its own Postgres database and role on the shared
    instance, injected as DATABASE_URL. Set false for stateless services or
    apps that use a different datastore.
  EOT
  type        = bool
  default     = true
}

variable "aws_region" {
  description = "Region to deploy into."
  type        = string
  default     = "us-east-1"
}

# --- Platform wiring (from the deploy config file) --------------------------

variable "platform_vpc_name" {
  description = "Name tag of the shared platform VPC."
  type        = string
  default     = "platform-vpc"
}

variable "platform_egress_sg_name" {
  description = "Name tag of the shared task egress SG that the platform RDS trusts."
  type        = string
  default     = "platform-ecs-egress"
}

variable "platform_db_identifier" {
  description = "Identifier of the shared RDS instance."
  type        = string
  default     = "platform-db"
}

variable "cluster_name" {
  description = "ECS cluster for Express services."
  type        = string
  default     = "default"
}

# --- Domain (OPTIONAL) ------------------------------------------------------

variable "custom_domain" {
  description = <<-EOT
    Full domain to serve the app on, e.g. "quoting.apps.example.com".

    Leave as "" to deploy with NO custom domain — the app is then reached at
    the AWS-provided *.on.aws URL. Note that raw *.on.aws URLs have no domain
    reputation and some corporate mail filters flag them, so anything you plan
    to send to a customer should have a domain.

    When set, hosted_zone_name must be the Route 53 zone containing it.
  EOT
  type        = string
  default     = ""
}

variable "hosted_zone_name" {
  description = "Route 53 public hosted zone containing custom_domain. Ignored when custom_domain is empty."
  type        = string
  default     = ""

  validation {
    condition     = var.hosted_zone_name == "" || can(regex("^[a-z0-9.-]+$", var.hosted_zone_name))
    error_message = "hosted_zone_name must be a bare DNS name like apps.example.com (no scheme, no path)."
  }
}

variable "origin_read_timeout" {
  description = "Seconds CloudFront waits on the origin. Raise for slow server actions or LLM calls."
  type        = number
  default     = 30
}

# --- Sizing -----------------------------------------------------------------

variable "cpu" {
  description = <<-EOT
    Fargate CPU units. 512 is the default and is right for most internal tools;
    measured PoCs on the old 1024 default sat under 1% CPU. Raise on evidence
    from CloudWatch, not on instinct.
  EOT
  type        = string
  default     = "512"
}

variable "memory" {
  description = "Fargate memory in MiB. 1024 is the practical floor for a Node server."
  type        = string
  default     = "1024"
}

variable "min_tasks" {
  description = "Minimum running tasks."
  type        = number
  default     = 1
}

variable "max_tasks" {
  description = "Autoscaling ceiling."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

# --- Application ------------------------------------------------------------

variable "environment_variables" {
  description = <<-EOT
    Extra non-secret env vars for the container, as {NAME = value}.
    Secrets do NOT go here — use app_secret_names so the value is injected from
    Secrets Manager at runtime instead of being stored in state.
  EOT
  type        = map(string)
  default     = {}
}

variable "app_secret_names" {
  description = <<-EOT
    Secret names this app needs, WITHOUT the project prefix, e.g.
    ["anthropic-api-key", "stripe-secret-key"].

    Terraform creates each secret with a REPLACE_ME placeholder and then
    ignores its value. Set the real values out-of-band so they never touch
    Terraform state or a file on disk:

      aws secretsmanager put-secret-value \
        --secret-id <service_name>/anthropic-api-key \
        --secret-string 'sk-ant-...'

    Each name becomes an env var in SCREAMING_SNAKE_CASE
    (anthropic-api-key -> ANTHROPIC_API_KEY).
  EOT
  type        = list(string)
  default     = []
}

variable "task_role_policy_json" {
  description = "IAM policy JSON for what the running app may call (S3, Bedrock, SES). Null for none."
  type        = string
  default     = null
}

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window. 0 for throwaway PoCs so a redeploy can reuse the name."
  type        = number
  default     = 7
}

# --- CI ---------------------------------------------------------------------

variable "github_owner" {
  description = "GitHub org or user."
  type        = string
}

variable "github_repo" {
  description = "Repository name."
  type        = string
}

variable "github_branch" {
  description = "Branch permitted to deploy."
  type        = string
  default     = "main"
}
