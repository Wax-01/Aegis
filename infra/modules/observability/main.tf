# -----------------------------------------------------------------------------
# CloudWatch por ambiente: /aegisvolt/<env>/<servicio>
# Los servicios escriben JSON con: service, environment, version, track, correlation_id, event, level...
# -----------------------------------------------------------------------------

locals {
  services = toset(var.services)
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.services
  name              = "/${var.project}/${var.environment}/${each.key}"
  retention_in_days = var.retention_days
  tags              = { Service = each.key }
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/${var.project}/${var.environment}/api-gateway"
  retention_in_days = var.retention_days
  tags              = { Service = "api-gateway" }
}

# --- Métricas derivadas de los logs (Metric Filters)
# Errores 5xx por servicio y por track (stable/canary): insumo del análisis Canary.
resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  for_each       = var.enable_metric_filters ? local.services : toset([])
  name           = "${var.project}-${var.environment}-${each.key}-http-5xx"
  log_group_name = aws_cloudwatch_log_group.service[each.key].name
  pattern        = "{ ($.event = \"http.request\") && ($.status >= 500) }"

  metric_transformation {
    name          = "Http5xx-${each.key}"
    namespace     = "AegisVolt/${var.environment}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "http_requests" {
  for_each       = var.enable_metric_filters ? local.services : toset([])
  name           = "${var.project}-${var.environment}-${each.key}-http-requests"
  log_group_name = aws_cloudwatch_log_group.service[each.key].name
  pattern        = "{ $.event = \"http.request\" }"

  metric_transformation {
    name          = "HttpRequests-${each.key}"
    namespace     = "AegisVolt/${var.environment}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "saga_compensated" {
  count          = var.enable_metric_filters ? 1 : 0
  name           = "${var.project}-${var.environment}-saga-compensated"
  log_group_name = aws_cloudwatch_log_group.service["graphql-gateway"].name
  pattern        = "{ $.event = \"saga.compensated\" }"

  metric_transformation {
    name          = "SagaCompensations"
    namespace     = "AegisVolt/${var.environment}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "saga_compensation_failed" {
  count          = var.enable_metric_filters ? 1 : 0
  name           = "${var.project}-${var.environment}-saga-compensation-failed"
  log_group_name = aws_cloudwatch_log_group.service["graphql-gateway"].name
  pattern        = "{ $.event = \"saga.compensation_failed\" }"

  metric_transformation {
    name          = "SagaCompensationFailures"
    namespace     = "AegisVolt/${var.environment}"
    value         = "1"
    default_value = "0"
  }
}

# Una compensación fallida deja datos inconsistentes: alarma inmediata.
resource "aws_cloudwatch_metric_alarm" "saga_compensation_failed" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${var.project}-${var.environment}-saga-compensation-failed"
  alarm_description   = "Una SAGA no pudo completar su rollback (COMPENSATION_FAILED). Ejecutar recoverSaga."
  namespace           = "AegisVolt/${var.environment}"
  metric_name         = "SagaCompensationFailures"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "gateway_5xx" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${var.project}-${var.environment}-graphql-gateway-5xx"
  alarm_description   = "Errores 5xx en la capa GraphQL (también evaluado por el análisis Canary)."
  namespace           = "AegisVolt/${var.environment}"
  metric_name         = "Http5xx-graphql-gateway"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}
