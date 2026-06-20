# This repo's OWN regional API Gateway. 10ulabs.com's CloudFront adds one origin
# (api_gateway_execute_domain) + one behavior for /wan-graph-designer/*, so every
# path under that prefix reaches this gateway. The gateway forwards /wan-graph-
# designer/{proxy+} to a single dispatching Lambda (deterministic name, created by
# the endpoints stack) that routes by path to the per-resource handlers.

locals {
  aws_region     = "us-east-2"
  aws_account_id = "781581267945"
  # The dispatching Lambda's name is fixed so the integration URI can be built
  # without a cross-stack remote_state read; the endpoints stack creates it and
  # grants invoke permission using this gateway's execution_arn (see outputs).
  lambda_name = "wan-graph-designer-api"
  lambda_invoke_arn = join("", [
    "arn:aws:apigateway:${local.aws_region}:lambda:path/2015-03-31/functions/",
    "arn:aws:lambda:${local.aws_region}:${local.aws_account_id}:function:",
    "${local.lambda_name}/invocations",
  ])
}

resource "aws_api_gateway_rest_api" "api" {
  name = "wan-graph-designer"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "product" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "wan-graph-designer"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.product.id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy_any" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy_any.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = local.lambda_invoke_arn
}

resource "aws_api_gateway_deployment" "prod" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.product.id,
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy_any.id,
      aws_api_gateway_integration.proxy.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.prod.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "prod"
}
