variable "aws_region" {
  description = "AWS region for the platform."
  type        = string
  default     = "us-east-1"
}

variable "admin_cidrs" {
  description = <<-EOT
    Operator IPs (CIDR, usually /32) allowed to reach the shared RDS on 5432.
    Needed so /deploy can create per-project databases and run migrations from
    the laptop. Update + `terraform apply` when your IP changes.
  EOT
  type        = list(string)
  default     = []
}

variable "db_instance_class" {
  description = "Shared RDS instance class. Bump (e.g. db.t4g.small) if projects outgrow it."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Initial allocated storage in GB (autoscales up to 100)."
  type        = number
  default     = 20
}
