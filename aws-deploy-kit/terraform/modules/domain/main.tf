###############################################################################
# modules/domain — branded HTTPS domain in front of an ECS Express service.
#
#   Route 53 (your domain) --ALIAS--> CloudFront (your ACM cert)
#       --origin Host = <svc>.on.aws--> Express shared ALB --> Fargate task
#
# WHY CLOUDFRONT AND NOT THE ALB DIRECTLY
# Express hands you a shared, Express-managed ALB that routes by host header.
# Hand-editing its listener rules works until the next Express update silently
# reverts them. CloudFront gives a stable, owned place to attach the cert.
#
# The managed AllViewerExceptHostHeader origin-request policy is load-bearing:
# it makes CloudFront send the ORIGIN hostname, which is what the ALB's
# host-header rule matches on. Forward the viewer host instead and every
# request 404s at the ALB.
#
# Entirely optional. A service with no domain simply doesn't call this module
# and is reached at its *.on.aws URL.
###############################################################################

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"

      # CloudFront certificates MUST be issued in us-east-1 regardless of where
      # the app runs, so the caller passes a us-east-1 provider as
      # `aws.us_east_1`. When the stack already lives in us-east-1 that is just
      # the same provider passed under the alias.
      configuration_aliases = [aws.us_east_1]
    }
  }
}

locals {
  # Strip any trailing dot so callers can pass either "example.com" or
  # "example.com." for the zone.
  zone_name = trimsuffix(var.hosted_zone_name, ".")
}

data "aws_route53_zone" "this" {
  name         = "${local.zone_name}."
  private_zone = false
}

# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "this" {
  provider = aws.us_east_1

  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = var.domain_name }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for dvo in aws_acm_certificate.this.domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.this.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

# Caching is disabled by default because these are dynamic, authenticated apps
# where a shared cache is a correctness hazard, not a speed win. Static assets
# are better served by the framework's own immutable-asset headers.
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.service_name} -> ECS Express Mode"
  aliases         = [var.domain_name]
  price_class     = var.price_class
  http_version    = "http2and3"

  origin {
    domain_name = var.origin_host
    origin_id   = "express"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = var.origin_read_timeout
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id       = "express"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.this.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = { Name = var.service_name }
}

resource "aws_route53_record" "this" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.this.domain_name
    zone_id                = aws_cloudfront_distribution.this.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "this_aaaa" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = var.domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.this.domain_name
    zone_id                = aws_cloudfront_distribution.this.hosted_zone_id
    evaluate_target_health = false
  }
}
