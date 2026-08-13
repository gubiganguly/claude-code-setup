variable "service_name" {
  description = "Project slug, used for tags and the distribution comment."
  type        = string
}

variable "domain_name" {
  description = <<-EOT
    Full domain to serve the app on, e.g. "quoting.apps.example.com" or
    "app.customer.com". Must sit inside hosted_zone_name.
  EOT
  type        = string
}

variable "hosted_zone_name" {
  description = <<-EOT
    Route 53 PUBLIC hosted zone that contains domain_name, e.g.
    "apps.example.com". Trailing dot optional. The zone must already exist and
    be authoritative (delegated at the registrar), or certificate validation
    hangs forever.
  EOT
  type        = string
}

variable "origin_host" {
  description = "Bare hostname of the Express endpoint (no scheme, no trailing slash). Use the service module's express_origin_host output."
  type        = string
}

variable "price_class" {
  description = "PriceClass_100 is North America and Europe only, and is the right default for internal tools."
  type        = string
  default     = "PriceClass_100"
}

variable "origin_read_timeout" {
  description = <<-EOT
    Seconds CloudFront waits for the origin to respond. Raise toward 60 for
    apps with slow server actions or long LLM calls; the default 30 will cut
    those off with a 504.
  EOT
  type        = number
  default     = 30
}
