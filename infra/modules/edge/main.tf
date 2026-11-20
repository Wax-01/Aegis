# -----------------------------------------------------------------------------
# Borde privado: API Gateway (REST) ─► VPC Link ─► NLB interno ─► NodePort del graphql-gateway en Kubernetes
#
# * API PRIVATE: solo invocable a través del Interface VPCE execute-api (resource policy aws:SourceVpce).
# * NLB interno en subredes privadas; sus targets son los nodos del clúster (NodePort del gateway).
# * PrivateLink hacia Kubernetes: VPC Endpoint Service sobre el NLB + Interface VPCE consumidor, para que
#   otros consumidores (p. ej. el worker de Prefect) lleguen al clúster sin salir a internet.
#
# En el emulador (Floci) el tipo de endpoint PRIVATE y el enrutamiento real de VPC no se emulan; se usa
# endpoint REGIONAL con integración directa al NodePort (variables api_endpoint_type / use_vpc_link).
# -----------------------------------------------------------------------------

locals {
  name       = "${var.project}-${var.environment}"
  is_private = var.api_endpoint_type == "PRIVATE"
}

# ---------------------------------------------------------------- NLB interno
resource "aws_lb" "k8s" {
  name               = "${local.name}-k8s-nlb"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.private_subnet_ids
  tags               = { Name = "${local.name}-k8s-nlb" }
}

resource "aws_lb_target_group" "graphql" {
  name        = "${local.name}-graphql"
  port        = var.gateway_node_port
  protocol    = "TCP"
  target_type = "instance"
  vpc_id      = var.vpc_id

  health_check {
    protocol            = "HTTP"
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 10
  }
}

resource "aws_lb_listener" "graphql" {
  load_balancer_arn = aws_lb.k8s.arn
  port              = 80
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.graphql.arn
  }
}

# Registra el Auto Scaling Group del node group de EKS en el target group (solo AWS real).
resource "aws_autoscaling_attachment" "nodes" {
  count                  = var.node_autoscaling_group_name != null ? 1 : 0
  autoscaling_group_name = var.node_autoscaling_group_name
  lb_target_group_arn    = aws_lb_target_group.graphql.arn
}

# ---------------------------------------------------------------- PrivateLink hacia Kubernetes
resource "aws_vpc_endpoint_service" "k8s" {
  count                      = var.enable_k8s_privatelink ? 1 : 0
  acceptance_required        = false
  network_load_balancer_arns = [aws_lb.k8s.arn]
  tags                       = { Name = "${local.name}-k8s-endpoint-service" }
}

resource "aws_vpc_endpoint" "k8s" {
  count               = var.enable_k8s_privatelink ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = aws_vpc_endpoint_service.k8s[0].service_name
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [var.vpce_security_group_id]
  private_dns_enabled = false
  tags                = { Name = "${local.name}-vpce-k8s" }
}

# ---------------------------------------------------------------- API Gateway
resource "aws_api_gateway_vpc_link" "k8s" {
  count       = var.use_vpc_link ? 1 : 0
  name        = "${local.name}-vpclink"
  target_arns = [aws_lb.k8s.arn]
}

resource "aws_api_gateway_rest_api" "this" {
  name        = "${local.name}-api"
  description = "AegisVolt GraphQL (${var.environment})"

  endpoint_configuration {
    types            = [var.api_endpoint_type]
    vpc_endpoint_ids = local.is_private ? [var.execute_api_vpce_id] : null
  }
}

data "aws_iam_policy_document" "private_api" {
  count = local.is_private ? 1 : 0

  statement {
    sid       = "AllowInvokeFromVpce"
    effect    = "Allow"
    actions   = ["execute-api:Invoke"]
    resources = ["${aws_api_gateway_rest_api.this.execution_arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  statement {
    sid       = "DenyOutsideVpce"
    effect    = "Deny"
    actions   = ["execute-api:Invoke"]
    resources = ["${aws_api_gateway_rest_api.this.execution_arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "aws:SourceVpce"
      values   = [var.execute_api_vpce_id]
    }
  }
}

resource "aws_api_gateway_rest_api_policy" "private" {
  count       = local.is_private ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.this.id
  policy      = data.aws_iam_policy_document.private_api[0].json
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id        = aws_api_gateway_rest_api.this.id
  resource_id        = aws_api_gateway_resource.proxy.id
  http_method        = "ANY"
  authorization      = "NONE"
  request_parameters = { "method.request.path.proxy" = true }
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = var.use_vpc_link ? "http://${aws_lb.k8s.dns_name}/{proxy}" : "${trimsuffix(var.direct_backend_url, "/")}/{proxy}"
  connection_type         = var.use_vpc_link ? "VPC_LINK" : "INTERNET"
  connection_id           = var.use_vpc_link ? aws_api_gateway_vpc_link.k8s[0].id : null
  request_parameters      = { "integration.request.path.proxy" = "method.request.path.proxy" }
  timeout_milliseconds    = 29000
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy.id,
      aws_api_gateway_integration.proxy.id,
      aws_api_gateway_integration.proxy.uri,
      try(aws_api_gateway_rest_api_policy.private[0].policy, ""),
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  deployment_id = aws_api_gateway_deployment.this.id
  stage_name    = var.environment

  dynamic "access_log_settings" {
    for_each = var.enable_access_logs ? [1] : []
    content {
      destination_arn = var.access_log_group_arn
      format = jsonencode({
        requestId          = "$context.requestId"
        ip                 = "$context.identity.sourceIp"
        sourceVpce         = "$context.identity.vpceId"
        httpMethod         = "$context.httpMethod"
        path               = "$context.path"
        status             = "$context.status"
        integrationLatency = "$context.integrationLatency"
        responseLatency    = "$context.responseLatency"
      })
    }
  }

  variables = {
    environment = var.environment
  }
}

resource "aws_api_gateway_method_settings" "all" {
  count       = var.enable_method_settings ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.this.id
  stage_name  = aws_api_gateway_stage.this.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    logging_level          = "INFO"
    throttling_rate_limit  = var.throttle_rate
    throttling_burst_limit = var.throttle_burst
  }
}
