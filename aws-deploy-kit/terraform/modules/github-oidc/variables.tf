variable "service_name" {
  description = "Project slug, used to name the role."
  type        = string
}

variable "github_owner" {
  description = "GitHub org or user that owns the repo."
  type        = string
}

variable "github_repo" {
  description = "Repository name (no owner prefix)."
  type        = string
}

variable "github_branch" {
  description = "Branch allowed to deploy. Anything else is refused at STS."
  type        = string
  default     = "main"
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repo CI pushes to."
  type        = string
}

variable "execution_role_arn" {
  description = "ECS execution role CI passes to the service."
  type        = string
}

variable "infrastructure_role_arn" {
  description = "ECS Express infrastructure role CI passes to the service."
  type        = string
}

variable "task_role_arn" {
  description = "Application task role CI passes to the service."
  type        = string
  default     = null
}

variable "cloudfront_distribution_arn" {
  description = "Grant CI permission to invalidate this distribution. Null to omit."
  type        = string
  default     = null
}
