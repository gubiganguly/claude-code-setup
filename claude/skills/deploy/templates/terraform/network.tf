###############################################################################
# network.tf — VPC, subnets, security groups
#
# Layout:
#   10.30.0.0/16   VPC
#     10.30.1.0/24 public  AZ a   (IGW — ECS Express tasks + ALB)
#     10.30.2.0/24 public  AZ b
#     10.30.11.0/24 private AZ a  (RDS)
#     10.30.12.0/24 private AZ b  (RDS)
#
# CIDR is 10.30.x (not 10.20.x) on purpose so this never collides with the
# LBMC Quoting stack if the two ever share an account.
#
# ECS Express Mode tasks run in the PUBLIC subnets: Express then provisions an
# internet-facing ALB and gives the tasks public IPs for egress via the IGW
# (no NAT gateway needed — that's a ~$32/mo saving vs the old App Runner setup).
# Tasks reach RDS in the private subnets over the in-VPC local route, gated by
# the RDS security group (which trusts the ECS task SG below).
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
# Public subnets + IGW (ECS Express tasks + internet-facing ALB live here)
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
# Private subnets (RDS only — no NAT, no internet route; reachable in-VPC)
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

# Plain route table (implicit local route only) so the private subnets have no
# path to the internet — RDS doesn't need one.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

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

# ECS Express task SG. No ingress here — Express manages ALB→task ingress on
# its own service SG; this SG is what RDS trusts. Egress wide open so tasks can
# pull from ECR / Secrets Manager (via IGW) and reach RDS.
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks"
  description = "Egress SG for ECS Express tasks (trusted by RDS)"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (IGW covers internet, RDS SG covers DB)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ecs-tasks"
  }
}

# RDS SG — only accept 5432 from the ECS task SG.
resource "aws_security_group" "rds_sg" {
  name        = "${var.project_name}-rds-sg"
  description = "Postgres access from ECS Express tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS Express tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
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
