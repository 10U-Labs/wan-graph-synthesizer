# This repo's OWN regional API Gateway, built from the OpenAPI spec (one Lambda
# per resource, registered via x-amazon-apigateway-integration). 10ulabs.com's
# CloudFront adds one origin (api_gateway_execute_domain) + one behavior for
# /wan-graph-synthesizer/*, so every route reaches this gateway. New endpoints are
# added by editing openapi.json + their own stack -- no change here.

module "common" {
  source = "../../../../lib/opentofu/common"
}

locals {
  aws_region     = module.common.aws_region
  aws_account_id = module.common.aws_account_id
  names          = module.common.lambda_handler_names

  apigw_prefix = "arn:aws:apigateway:${local.aws_region}:lambda:path/2015-03-31/functions"
  lambda_arn   = "arn:aws:lambda:${local.aws_region}:${local.aws_account_id}:function"

  # Integration ARN per Lambda function name (built without a cross-stack read;
  # each endpoint stack creates its function with this deterministic name).
  integration = {
    for key, name in local.names :
    key => "${local.apigw_prefix}/${local.lambda_arn}:${name}/invocations"
  }

  openapi_spec = templatefile("${path.module}/../../../www/api/openapi.json", {
    CarriersHandlerArn  = local.integration.carriers
    CspsHandlerArn      = local.integration.csps
    CustomersHandlerArn = local.integration.customers
    MergeHandlerArn     = local.integration.merge
    WanHandlerArn       = local.integration.wan
  })
  spec_hash = substr(md5(local.openapi_spec), 0, 8)
}

resource "aws_api_gateway_rest_api" "api" {
  name = "wan-graph-synthesizer"
  body = local.openapi_spec

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_deployment" "prod" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeploy = local.spec_hash
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
