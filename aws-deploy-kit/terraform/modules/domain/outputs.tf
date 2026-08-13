output "url" {
  description = "The branded HTTPS URL. This is the one to share."
  value       = "https://${var.domain_name}"
}

output "domain_name" {
  description = "The domain serving the app."
  value       = var.domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID — use for invalidations and status checks."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_domain_name" {
  description = "The *.cloudfront.net name behind the alias."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "certificate_arn" {
  description = "Validated ACM certificate ARN."
  value       = aws_acm_certificate_validation.this.certificate_arn
}
