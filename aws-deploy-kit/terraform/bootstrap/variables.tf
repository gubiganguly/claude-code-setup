variable "aws_region" {
  description = "Region the state bucket lives in. Every other stack must use the same value in its backend block."
  type        = string
  default     = "us-east-1"
}

variable "org_slug" {
  description = <<-EOT
    Short lowercase identifier for the organisation that owns this account
    (e.g. "snh", "lbmc", "acme"). Used to name the state bucket and KMS alias.
    Pick one and never change it — renaming means migrating state.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,20}$", var.org_slug))
    error_message = "org_slug must be 2-21 chars, lowercase alphanumeric or hyphen, starting with alphanumeric."
  }
}

variable "state_bucket_name" {
  description = <<-EOT
    Override the generated state bucket name. Leave null to use
    "<org_slug>-tfstate-<account_id>", which is unique without any thought.
    Set this only when adopting a bucket that already exists.
  EOT
  type        = string
  default     = null
}

variable "create_github_oidc_provider" {
  description = <<-EOT
    Create the GitHub Actions OIDC provider. Only ONE can exist per AWS
    account, so set this to false if the account already has one (apply will
    otherwise fail with EntityAlreadyExists). Check with:
      aws iam list-open-id-connect-providers
  EOT
  type        = bool
  default     = true
}
