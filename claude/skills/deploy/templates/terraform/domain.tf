###############################################################################
# domain.tf — Custom domain: <project>.apps.snhcap.com
#
# apps.snhcap.com is a Route 53 zone owned by the platform stack (delegated
# from GoDaddy). This file associates <project>.apps.snhcap.com with the App
# Runner service, creates the certificate-validation CNAMEs, and points the
# domain at the service. AWS issues + renews the certificate automatically.
#
# APPLY ORDER (matters): the validation records aren't known until the
# association exists, so the FIRST apply must be two-phase:
#   terraform apply -target=aws_apprunner_custom_domain_association.app
#   terraform apply
# (Subsequent applies are normal.) Certificate issuance takes ~5-15 min after
# the records land; the domain serves traffic once status is "active":
#   aws apprunner describe-custom-domains --service-arn <arn>
#
# Delete this file if the project shouldn't get a custom domain.
###############################################################################

data "aws_route53_zone" "apps" {
  name = "apps.snhcap.com."
}

locals {
  app_domain = "${var.project_name}.apps.snhcap.com"
}

resource "aws_apprunner_custom_domain_association" "app" {
  domain_name          = local.app_domain
  service_arn          = aws_apprunner_service.app.arn
  enable_www_subdomain = false
}

# Certificate validation CNAMEs (AWS proves we own the domain, then issues
# and auto-renews the TLS cert).
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for r in aws_apprunner_custom_domain_association.app.certificate_validation_records :
    r.name => r
  }

  zone_id = data.aws_route53_zone.apps.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.value]
  ttl     = 300
}

# The domain itself → the App Runner service.
resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.apps.zone_id
  name    = local.app_domain
  type    = "CNAME"
  records = [aws_apprunner_custom_domain_association.app.dns_target]
  ttl     = 300
}

output "custom_domain" {
  description = "Branded HTTPS URL of the app."
  value       = "https://${local.app_domain}"
}
