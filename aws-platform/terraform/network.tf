###############################################################################
# network.tf — Shared VPC, subnets, NAT, security groups.
#
# Layout (10.10.x chosen to avoid csip 10.30, dice 10.40, lbmc 10.20):
#   10.10.0.0/16    VPC
#     10.10.1.0/24  public  AZ a   (NAT, RDS)
#     10.10.2.0/24  public  AZ b   (RDS)
#     10.10.11.0/24 private AZ a   (App Runner VPC connector ENIs)
#     10.10.12.0/24 private AZ b
#
# Private subnets route 0.0.0.0/0 through the single NAT — that's what gives
# every project's App Runner service outbound internet (external APIs) while
# keeping its ENIs unaddressable from outside.
###############################################################################

locals {
  vpc_cidr             = "10.10.0.0/16"
  public_subnet_cidrs  = ["10.10.1.0/24", "10.10.2.0/24"]
  private_subnet_cidrs = ["10.10.11.0/24", "10.10.12.0/24"]
  azs                  = ["${var.aws_region}a", "${var.aws_region}b"]
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "platform-vpc"
  }
}

# ---------------------------------------------------------------------------
# Public subnets + IGW
# ---------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count                   = length(local.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "platform-public-${count.index}"
    Tier = "public"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "platform-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "platform-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# Private subnets + single NAT
# ---------------------------------------------------------------------------

resource "aws_subnet" "private" {
  count             = length(local.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "platform-private-${count.index}"
    Tier = "private"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "platform-nat-eip"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "platform-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "platform-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

# Source SG for ALL projects' App Runner VPC connectors. No ingress — App
# Runner is always the client.
resource "aws_security_group" "app_runner_egress" {
  name        = "platform-app-runner-egress"
  description = "Shared egress SG for App Runner VPC connector"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (NAT covers internet, RDS SG covers DB)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-app-runner-egress"
  }
}

# Source SG for ALL projects' ECS Express Mode tasks. No ingress — Express
# manages ALB→task ingress on its own service SG; this SG is what RDS trusts.
resource "aws_security_group" "ecs_egress" {
  name        = "platform-ecs-egress"
  description = "Shared egress SG for ECS Express tasks"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (IGW/NAT covers internet, RDS SG covers DB)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-ecs-egress"
  }
}

# Shared RDS SG: Postgres from App Runner services (via the egress SG) and
# from the operator's IP (admin_cidrs) so /deploy can create per-project
# databases and run migrations from the laptop. Update admin_cidrs in
# terraform.tfvars + re-apply when your IP changes.
resource "aws_security_group" "rds_sg" {
  name        = "platform-rds-sg"
  description = "Postgres access from App Runner + operator IPs"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from App Runner VPC connector"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_runner_egress.id]
  }

  ingress {
    description     = "Postgres from ECS Express tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_egress.id]
  }

  dynamic "ingress" {
    for_each = var.admin_cidrs
    content {
      description = "Postgres from operator IP"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-rds-sg"
  }
}
