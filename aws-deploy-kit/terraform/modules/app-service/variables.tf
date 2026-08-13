variable "service_name" {
  description = "Short slug. Names the ECR repo, ECS service, log group, and IAM roles. Lowercase, hyphens allowed."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}$", var.service_name))
    error_message = "service_name must be 2-31 chars, lowercase alphanumeric or hyphen."
  }
}

variable "cluster_name" {
  description = "ECS cluster. Express services share one cluster per account by convention."
  type        = string
  default     = "default"
}

# --- Container contract -----------------------------------------------------

variable "container_port" {
  description = "Port the container listens on. 3000 for Next.js, 8000 for FastAPI, 8080 for most JVM/Go apps."
  type        = number
  default     = 3000
}

variable "health_check_path" {
  description = <<-EOT
    Path the ALB polls. MUST return 200 without authentication — if the app has
    auth middleware, exclude this path from its matcher or the service will
    never stabilise.
  EOT
  type        = string
  default     = "/health"
}

variable "initial_image_tag" {
  description = <<-EOT
    Tag Terraform points at when it first creates the service. An image with
    this tag must already exist in ECR (scripts/bootstrap-image.sh pushes one).
    After creation, CI owns the tag and Terraform ignores image drift.
  EOT
  type        = string
  default     = "bootstrap"
}

# --- Sizing -----------------------------------------------------------------

variable "cpu" {
  description = <<-EOT
    Fargate CPU units as a string: "256", "512", "1024", "2048", "4096".
    Default is 512 (0.5 vCPU). v1 defaulted to 1024 and every PoC deployed with
    it sat under 1% CPU, so start small and raise on evidence.
  EOT
  type        = string
  default     = "512"

  validation {
    condition     = contains(["256", "512", "1024", "2048", "4096", "8192", "16384"], var.cpu)
    error_message = "cpu must be a valid Fargate value: 256, 512, 1024, 2048, 4096, 8192, or 16384."
  }
}

variable "memory" {
  description = "Fargate memory in MiB as a string. Must be a legal pairing with cpu. 1024 is the practical floor for Node."
  type        = string
  default     = "1024"
}

variable "min_tasks" {
  description = "Minimum running tasks. 1 for anything with users; see the preset docs before setting 0."
  type        = number
  default     = 1
}

variable "max_tasks" {
  description = "Autoscaling ceiling."
  type        = number
  default     = 10
}

variable "scaling_cpu_target" {
  description = "Average CPU percent the autoscaler aims to hold."
  type        = number
  default     = 60
}

# --- Networking -------------------------------------------------------------

variable "subnet_ids" {
  description = <<-EOT
    PUBLIC subnet IDs. Express infers ALB scheme from subnet type: private
    subnets yield an INTERNAL ALB (no public URL) and require a NAT gateway.
    Pass public subnets unless you specifically want an internal service.
  EOT
  type        = list(string)
}

variable "security_group_ids" {
  description = "SGs for the task ENI. Needs egress; needs no ingress (Express manages ALB-to-task on its own SG)."
  type        = list(string)
}

# --- App configuration ------------------------------------------------------

variable "environment" {
  description = "Non-secret env vars as {NAME = value}."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = <<-EOT
    Secret env vars as {NAME = secret_arn}. ECS injects the value at task
    launch; it never appears in the task definition or in Terraform state.
    To pull one key out of a JSON secret, append ":<key>::" to the ARN.
  EOT
  type        = map(string)
  default     = {}
}

variable "task_role_policy_json" {
  description = "IAM policy JSON for what the APP may call at runtime (S3, Bedrock, SES...). Null means no runtime permissions."
  type        = string
  default     = null
}

# --- Housekeeping -----------------------------------------------------------

variable "log_retention_days" {
  description = "CloudWatch retention. 30 is a reasonable default; raise for anything audited."
  type        = number
  default     = 30
}

variable "ecr_keep_tagged_images" {
  description = "How many SHA-tagged images to retain. This is the rollback window."
  type        = number
  default     = 15
}
