variable "service_name" {
  description = "Project slug. The database becomes <slug_with_underscores> and the role <slug>_app."
  type        = string
}

variable "db_host" {
  description = "RDS endpoint address (no port)."
  type        = string
}

variable "db_port" {
  description = "RDS port."
  type        = number
  default     = 5432
}

variable "master_secret_arn" {
  description = <<-EOT
    Secrets Manager ARN of the RDS-managed master credential (JSON with
    username/password). Read ONLY by the provisioning task, never by the app.
  EOT
  type        = string
}

variable "master_database" {
  description = "Database the provisioner connects to in order to create the new one."
  type        = string
  default     = "postgres"
}

variable "cluster_name" {
  description = "ECS cluster used to run the one-shot provisioning task."
  type        = string
  default     = "default"
}

variable "subnet_ids" {
  description = "Subnets for the provisioning task. Must have a network path to RDS."
  type        = list(string)
}

variable "security_group_ids" {
  description = "SGs for the provisioning task. Must be trusted by the RDS security group on 5432."
  type        = list(string)
}

variable "assign_public_ip" {
  description = <<-EOT
    Give the provisioning task a public IP. Required when it runs in PUBLIC
    subnets, because Fargate needs a route to pull its image and reach the
    Secrets Manager and ECR endpoints. Set false only for private subnets that
    have a NAT gateway or the relevant VPC endpoints.
  EOT
  type        = bool
  default     = true
}

variable "provisioner_image" {
  description = <<-EOT
    Image providing psql and pg_isready. The public ECR mirror avoids Docker
    Hub rate limits, which is the usual cause of a first-deploy failure here.
  EOT
  type        = string
  default     = "public.ecr.aws/docker/library/postgres:17-alpine"
}

variable "sslmode" {
  description = <<-EOT
    libpq sslmode for the application's connection string. "require" encrypts
    without verifying the CA. Use "verify-full" once the RDS CA bundle is
    baked into the app image — that is the correct end state, and v1's
    "no-verify" was weaker than either.
  EOT
  type        = string
  default     = "require"
}

variable "secret_recovery_window_days" {
  description = <<-EOT
    Secrets Manager recovery window. 0 deletes immediately, which is what you
    want for short-lived PoCs — otherwise a destroy-then-redeploy collides
    with the soft-deleted secret name.
  EOT
  type        = number
  default     = 7
}
