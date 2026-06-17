###############################################################################
# route53.tf — DNS zone for app custom domains.
#
# apps.snhcap.com is DELEGATED from GoDaddy (where snhcap.com itself lives):
# GoDaddy has NS records for "apps" pointing at this zone's name servers
# (see the apps_zone_name_servers output). Everything under apps.snhcap.com
# is then managed here / by project deploys — each shared-mode project gets
# <project>.apps.snhcap.com with an auto-issued certificate.
#
# If this zone is ever destroyed and recreated, AWS assigns NEW name servers
# and the GoDaddy NS records must be updated to match.
###############################################################################

resource "aws_route53_zone" "apps" {
  name    = "apps.snhcap.com"
  comment = "App custom domains — delegated from GoDaddy; per-app records created by project deploys"

  tags = {
    Name = "apps.snhcap.com"
  }
}

output "apps_zone_id" {
  description = "Hosted zone ID for apps.snhcap.com."
  value       = aws_route53_zone.apps.zone_id
}

output "apps_zone_name_servers" {
  description = "Name servers to set as NS records for 'apps' at GoDaddy (snhcap.com DNS)."
  value       = aws_route53_zone.apps.name_servers
}
