output "state_bucket" {
  description = "S3 bucket holding Terraform state for every stack in this account."
  value       = aws_s3_bucket.state.id
}

output "state_kms_key_arn" {
  description = "KMS key encrypting state objects."
  value       = aws_kms_key.state.arn
}

output "github_oidc_provider_arn" {
  description = "GitHub Actions OIDC provider ARN — consumed by every project's deploy role."
  value = var.create_github_oidc_provider ? (
    aws_iam_openid_connect_provider.github[0].arn
  ) : data.aws_iam_openid_connect_provider.github_existing[0].arn
}

# The whole point of this stack: a copy-pasteable backend block. Every other
# stack gets this same block with a different `key`.
output "backend_config" {
  description = "Paste into the terraform{} block of every other stack, changing only `key`."
  value       = <<-EOT
    backend "s3" {
      bucket       = "${aws_s3_bucket.state.id}"
      key          = "CHANGE-ME/terraform.tfstate"
      region       = "${var.aws_region}"
      encrypt      = true
      kms_key_id   = "${aws_kms_key.state.arn}"
      use_lockfile = true
    }
  EOT
}
