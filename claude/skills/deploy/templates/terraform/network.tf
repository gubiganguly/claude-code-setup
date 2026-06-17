###############################################################################
# network.tf — VPC, subnets, NAT, security groups
#
# Layout:
#   10.30.0.0/16   VPC
#     10.30.1.0/24 public  AZ a   (NAT + IGW attachment)
#     10.30.2.0/24 public  AZ b
#     10.30.11.0/24 private AZ a  (RDS)
#     10.30.12.0/24 private AZ b  (RDS)
#
# CIDR is 10.30.x (not 10.20.x) on purpose so this never collides with the
# LBMC Quoting stack if the two ever share an account.
#
# App Runner is run as a managed service outside the VPC. The VPC Connector
# pins egress to the PUBLIC subnets so the NAT route lets it talk to ECR,
# Secrets Manager, and the RDS endpoint (which lives in the private subnets).
###############################################################################

locals {
  vpc_cidr             = "10.30.0.0/16"
  public_subnet_cidrs  = ["10.30.1.0/24", "10.30.2.0/24"]
  private_subnet_cidrs = ["10.30.11.0/24", "10.30.12.0/24"]
  azs                  = ["${var.aws_region}a", "${var.aws_region}b"]
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc"
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
    Name = "${var.project_name}-public-${count.index}"
    Tier = "public"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# Private subnets + single NAT (PoC scope — one NAT, not one per AZ)
# ---------------------------------------------------------------------------

resource "aws_subnet" "private" {
  count             = length(local.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${var.project_name}-private-${count.index}"
    Tier = "private"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-nat-eip"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${var.project_name}-nat"
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
    Name = "${var.project_name}-private-rt"
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

# App Runner VPC Connector source SG. No ingress — App Runner is the client.
# Egress wide open so it can pull from ECR public endpoints, Secrets Manager,
# and reach RDS.
resource "aws_security_group" "app_runner_egress" {
  name        = "${var.project_name}-app-runner-egress"
  description = "Egress SG for App Runner VPC connector"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (NAT covers internet, RDS SG covers DB)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-app-runner-egress"
  }
}

# RDS SG — only accept 5432 from the App Runner egress SG.
resource "aws_security_group" "rds_sg" {
  name        = "${var.project_name}-rds-sg"
  description = "Postgres access from App Runner only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from App Runner VPC connector"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_runner_egress.id]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-rds-sg"
  }
}
