variable "aws_region" {
  description = "Region for the platform."
  type        = string
  default     = "us-east-1"
}

variable "platform_name" {
  description = "Prefix for platform resource names. Projects discover the VPC by \"<platform_name>-vpc\"."
  type        = string
  default     = "platform"
}

variable "vpc_cidr" {
  description = "CIDR for the shared VPC. Must not overlap any VPC you might later peer with."
  type        = string
  default     = "10.10.0.0/16"
}

variable "cluster_name" {
  description = "ECS cluster name shared by every Express service in the account."
  type        = string
  default     = "default"
}

variable "container_insights" {
  description = <<-EOT
    Enable ECS Container Insights. Gives per-task CPU and memory metrics, which
    is what right-sizing decisions need. Costs a few dollars a month and is
    worth it the first time you have to size a service.
  EOT
  type        = bool
  default     = true
}

# --- Database ---------------------------------------------------------------

variable "db_identifier" {
  description = "RDS instance identifier. Projects look the instance up by this name."
  type        = string
  default     = "platform-db"
}

variable "db_engine_version" {
  description = "Postgres major version."
  type        = string
  default     = "17"
}

variable "db_instance_class" {
  description = "db.t4g.micro carries a surprising number of small apps. Scale up when connections or CPU say so."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Initial storage."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling."
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Multi-AZ roughly doubles database cost. Off for internal tools, on for anything customer-facing."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Automated backup retention."
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = <<-EOT
    Leave this on. Every project in the account keeps its data on this one
    instance, so an accidental destroy here is the worst thing that can happen
    to the platform.
  EOT
  type        = bool
  default     = true
}

variable "db_performance_insights" {
  description = "Performance Insights. Free at 7-day retention and the fastest way to find a slow query."
  type        = bool
  default     = true
}

# --- DNS --------------------------------------------------------------------

variable "hosted_zone_name" {
  description = <<-EOT
    Public Route 53 zone for branded app domains, e.g. "apps.example.com".
    Leave "" to skip DNS entirely (apps then use their *.on.aws URLs).

    After creating it, delegate the zone at your registrar using the name
    servers in the hosted_zone_name_servers output. Skip that step and ACM
    certificate validation will hang indefinitely.
  EOT
  type        = string
  default     = ""
}
