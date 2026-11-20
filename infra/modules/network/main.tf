# -----------------------------------------------------------------------------
# Red dedicada por ambiente: VPC + subredes públicas/privadas en 2 AZ + VPC Endpoints.
#
# Recorrido privado de un request (AWS real):
#   cliente en la VPC ─► Interface VPCE execute-api (ENIs en subredes privadas, SG vpce: 443 desde la VPC)
#   ─► API Gateway PRIVATE (resource policy: solo aws:SourceVpce = este endpoint)
#   ─► VPC Link ─► NLB interno (subredes privadas) ─► NodePort en los nodos EKS (SG nodes) ─► Service ─► Pod
#   Pod ─► DynamoDB/S3 por Gateway VPCE (entrada prefix-list en la route table PRIVADA, sin NAT ni internet)
#   Pod ─► CloudWatch Logs/Metrics por Interface VPCE (DNS privado resuelve logs.<region>.amazonaws.com a ENIs)
# -----------------------------------------------------------------------------

locals {
  name = "${var.project}-${var.environment}"
  azs  = slice(var.availability_zones, 0, var.az_count)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # requerido para private_dns_enabled en los Interface VPCE
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = length(local.azs)
  vpc_id                  = aws_vpc.this.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags = {
    Name                     = "${local.name}-public-${local.azs[count.index]}"
    Tier                     = "public"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  tags = {
    Name                              = "${local.name}-private-${local.azs[count.index]}"
    Tier                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# --- Ruteo público: 0.0.0.0/0 -> Internet Gateway
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-rt-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- Ruteo privado: sin salida a internet salvo NAT opcional. El tráfico a S3/DynamoDB sale por los
#     Gateway Endpoints (rutas prefix-list que AWS agrega a esta tabla automáticamente).
resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }
}

resource "aws_nat_gateway" "this" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${local.name}-nat" }
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-rt-private" }
}

resource "aws_route" "private_nat" {
  count                  = var.enable_nat_gateway ? 1 : 0
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- Security Groups
resource "aws_security_group" "vpce" {
  name        = "${local.name}-vpce"
  description = "Interface VPC Endpoints: HTTPS solo desde la VPC"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS desde la VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = { Name = "${local.name}-sg-vpce" }
}

resource "aws_security_group" "k8s_nodes" {
  name        = "${local.name}-k8s-nodes"
  description = "Nodos Kubernetes: NodePorts solo desde la VPC (NLB interno / VPC Link)"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "NodePort range desde la VPC"
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "Trafico entre nodos"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-sg-k8s-nodes" }
}

# --- Gateway VPC Endpoints (S3 y DynamoDB): sin costo, se asocian a la route table privada.
data "aws_iam_policy_document" "dynamodb_endpoint" {
  statement {
    sid       = "OnlyThisEnvironmentTables"
    effect    = "Allow"
    actions   = ["dynamodb:*"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:*:table/${var.project}-*-${var.environment}*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  policy            = data.aws_iam_policy_document.dynamodb_endpoint.json
  tags              = { Name = "${local.name}-vpce-dynamodb" }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${local.name}-vpce-s3" }
}

# --- Interface VPC Endpoints (PrivateLink): ENIs en las subredes privadas con DNS privado.
#     execute-api  -> API Gateway PRIVATE
#     logs         -> CloudWatch Logs (logs JSON de los pods)
#     monitoring   -> CloudWatch Metrics (métricas del canary)
#     sts          -> IRSA (pods asumiendo roles IAM)
resource "aws_vpc_endpoint" "interface" {
  for_each = var.enable_interface_endpoints ? toset(var.interface_endpoint_services) : toset([])

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "${local.name}-vpce-${each.value}" }
}
