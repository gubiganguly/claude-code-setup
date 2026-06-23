###############################################################################
# domain.tf — Branded domain: <project>.apps.snhcap.com via CloudFront.
#
# ECS Express Mode hands us an AWS-provided `*.on.aws` URL fronted by a SHARED,
# black-box ALB (host-header routed). It has no clean custom-domain primitive,
# and hand-editing its listener rules risks being clobbered on the next Express
# update. So we put CloudFront in front:
#
#   Route 53 (<project>.apps.snhcap.com)  ──ALIAS──▶  CloudFront (our ACM cert)
#       ──origin Host = <project>.on.aws──▶  Express shared ALB ──▶ Fargate task
#
# CloudFront sends the ORIGIN's hostname as the Host header (we attach the
# managed AllViewerExceptHostHeader origin-request policy), so the ALB's
# host-header rule for the `*.on.aws` name still matches.
#
# apps.snhcap.com is a Route 53 zone owned by the platform stack (delegated
# from GoDaddy). Delete this file if the project shouldn't get a branded domain.
#
# Two-phase first apply: the Express `*.on.aws` URL isn't known until the
# service exists, so the very first run is:
#   terraform apply -target=aws_ecs_express_gateway_service.app
#   terraform apply
###############################################################################

variable "express_origin_host" {
  description = <<-EOT
    The Express Mode `*.on.aws` hostname (no scheme, no path) used as the
    CloudFront origin. Leave blank to derive it automatically from the service's
    ingress_paths attribute; set it explicitly only if that derivation fails
    (read it with: aws ecs describe-express-gateway-service --service-name <project>).
  EOT
  type        = string
  default     = ""
}

locals {
  app_domain = "${var.project_name}.apps.snhcap.com"

  # Prefer an explicit override; otherwise pull the AWS-provided endpoint out of
  # the service's ingress_paths (a list of {access_type, endpoint}) and strip
  # any scheme/trailing slash down to a bare hostname for the CloudFront origin.
  derived_origin_host = try(
    replace(
      replace(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, "https://", ""),
      "/",
      "",
    ),
    "",
  )

  express_origin_host = coalesce(
    var.express_origin_host != "" ? var.express_origin_host : null,
    local.derived_origin_host != "" ? local.derived_origin_host : null,
  )
}

data "aws_route53_zone" "apps" {
  name = "apps.snhcap.com."
}

# ---------------------------------------------------------------------------
# ACM certificate for the branded domain (CloudFront requires us-east-1, which
# is also our deploy region — no separate provider alias needed).
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "app" {
  domain_name       = local.app_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = local.app_domain
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.app.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = data.aws_route53_zone.apps.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# ---------------------------------------------------------------------------
# CloudFront — branded TLS in front of the Express `*.on.aws` URL.
# ---------------------------------------------------------------------------

# Managed policies: don't cache (the app is dynamic/SSR + auth), and forward
# everything to the origin EXCEPT the viewer Host header — so CloudFront sends
# the origin (`*.on.aws`) hostname, which the Express ALB routes on.
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "app" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.project_name} → ECS Express Mode"
  aliases         = [local.app_domain]
  price_class     = "PriceClass_100"

  origin {
    domain_name = local.express_origin_host
    origin_id   = "express"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "express"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]

    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.app.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Name = var.project_name
  }
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.apps.zone_id
  name    = local.app_domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.app.domain_name
    zone_id                = aws_cloudfront_distribution.app.hosted_zone_id
    evaluate_target_health = false
  }
}

output "custom_domain" {
  description = "Branded HTTPS URL of the app."
  value       = "https://${local.app_domain}"
}
