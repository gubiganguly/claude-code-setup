###############################################################################
# platform/main.tf — the shared, standing infrastructure for one AWS account.
#
# Run ONCE per account, after bootstrap. Every project deploy then plugs into
# it and creates only per-project resources.
#
# WHAT CHANGED FROM v1, AND WHY
#
#  * RDS is no longer publicly accessible. v1 needed public access because it
#    created databases by running psql from the operator's laptop. v2 runs that
#    inside the VPC (modules/database), so the instance can be private and the
#    admin-IP allowlist disappears entirely.
#
#  * No NAT gateway. Application tasks sit in public subnets and egress via the
#    internet gateway; RDS sits in private subnets and needs no outbound path
#    at all. That removes ~$32/mo of fixed cost and one more thing to explain.
#
#  * Subnets are tagged Tier=public|private so projects can discover them by
#    tag instead of having subnet IDs pasted into their tfvars.
#
# COST: RDS db.t4g.micro (~$13/mo) plus whatever the projects themselves run.
###############################################################################

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }

  # From the bootstrap stack's `backend_config` output.
  backend "s3" {
    bucket       = "REPLACE_ME-tfstate-000000000000"
    key          = "platform/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      ManagedBy = "terraform"
      Stack     = "platform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs           = slice(data.aws_availability_zones.available.names, 0, 2)
  public_cidrs  = [cidrsubnet(var.vpc_cidr, 8, 1), cidrsubnet(var.vpc_cidr, 8, 2)]
  private_cidrs = [cidrsubnet(var.vpc_cidr, 8, 11), cidrsubnet(var.vpc_cidr, 8, 12)]
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.platform_name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.platform_name}-igw" }
}

# Public: application tasks. They get public IPs for egress (cheaper than a NAT
# at this scale) but are reachable only through the Express-managed ALB.
resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.platform_name}-public-${count.index}"
    Tier = "public"
  }
}

# Private: RDS only. No NAT and no IGW route, so there is no path to or from
# the internet. The database is reachable from the public subnets over the
# VPC-local route, which is all any task needs.
resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${var.platform_name}-private-${count.index}"
    Tier = "private"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.platform_name}-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Deliberately has no 0.0.0.0/0 route. The VPC-local route is implicit.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.platform_name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

# Worn by every project's tasks and by the database provisioner. No ingress:
# Express manages ALB-to-task traffic on its own service SG.
resource "aws_security_group" "ecs_egress" {
  name        = "${var.platform_name}-ecs-egress"
  description = "Shared egress SG for ECS tasks; trusted by the platform RDS"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.platform_name}-ecs-egress" }
}

# Postgres from the shared task SG and nothing else. v1 also had to admit the
# operator's laptop IP; in-VPC provisioning made that unnecessary.
resource "aws_security_group" "rds" {
  name        = "${var.platform_name}-rds"
  description = "Postgres from platform ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from platform ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_egress.id]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.platform_name}-rds" }
}

# ---------------------------------------------------------------------------
# Shared database
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name        = "${var.platform_name}-db"
  description = "Private subnets for the shared platform database"
  subnet_ids  = aws_subnet.private[*].id

  tags = { Name = "${var.platform_name}-db" }
}

resource "aws_db_instance" "main" {
  identifier     = var.db_identifier
  engine         = "postgres"
  engine_version = var.db_engine_version

  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "platform"
  username = "platform_admin"

  # Master credentials are AWS-managed and AWS-rotated. Only the in-VPC
  # provisioning task ever reads them; applications connect as their own role.
  manage_master_user_password = true

  vpc_security_group_ids = [aws_security_group.rds.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name

  # The whole point of v2's in-VPC provisioning.
  publicly_accessible = false

  multi_az = var.db_multi_az

  backup_retention_period   = var.db_backup_retention_days
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.db_identifier}-final"
  apply_immediately         = true

  auto_minor_version_upgrade   = true
  performance_insights_enabled = var.db_performance_insights

  tags = { Name = var.db_identifier }
}

# ---------------------------------------------------------------------------
# Shared ECS cluster
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = var.cluster_name

  setting {
    name  = "containerInsights"
    value = var.container_insights ? "enabled" : "disabled"
  }

  tags = { Name = var.cluster_name }
}

# ---------------------------------------------------------------------------
# DNS zone for branded app domains (optional)
#
# Create this only if you want <app>.<zone> domains. Delegate it at your
# registrar with the name servers in the `hosted_zone_name_servers` output, or
# certificate validation will hang forever.
# ---------------------------------------------------------------------------

resource "aws_route53_zone" "apps" {
  count = var.hosted_zone_name == "" ? 0 : 1

  name    = var.hosted_zone_name
  comment = "Branded domains for apps deployed on ${var.platform_name}"

  tags = { Name = var.hosted_zone_name }
}
