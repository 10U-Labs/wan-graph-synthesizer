provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      ManagedBy  = "OpenTofu"
      Project    = "wan-graph-synthesizer"
      Repository = "10U-Labs/wan-graph-synthesizer"
      Stack      = "endpoints/carriers"
    }
  }
}

module "common" {
  source = "../../../../lib/opentofu/common"
}

locals {
  function_name = module.common.lambda_handler_names.carriers
  role_name     = "wan-graph-synthesizer-carriers-lambda"

  lambda_arn_prefix = "arn:aws:lambda:${module.common.aws_region}:${module.common.aws_account_id}:function"
  cascade_function_arns = [
    "${local.lambda_arn_prefix}:${module.common.lambda_handler_names.merge}",
    "${local.lambda_arn_prefix}:${module.common.lambda_handler_names.wan}",
  ]
}

data "terraform_remote_state" "routing" {
  backend = "s3"

  config = {
    bucket = module.common.state_bucket
    key    = "wan-graph-synthesizer/common/routing/terraform.tfstate"
    region = module.common.aws_region
  }
}

data "terraform_remote_state" "storage" {
  backend = "s3"

  config = {
    bucket = module.common.state_bucket
    key    = "wan-graph-synthesizer/common/storage/terraform.tfstate"
    region = module.common.aws_region
  }
}

data "archive_file" "handler" {
  type        = "zip"
  source_file = "${path.module}/lambdas/handler.py"
  output_path = "${path.module}/.terraform/lambda_packages/handler.zip"
}

resource "aws_lambda_function" "handler" {
  filename         = data.archive_file.handler.output_path
  function_name    = local.function_name
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.handler.output_base64sha256
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 10
  memory_size      = 128
  description      = "Carriers read endpoint: serve a carrier's graph from the store."

  environment {
    variables = {
      STORE_BUCKET   = data.terraform_remote_state.storage.outputs.bucket_name
      MERGE_FUNCTION = module.common.lambda_handler_names.merge
      WAN_FUNCTION   = module.common.lambda_handler_names.wan
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.handler.name
  }

  lifecycle {
    replace_triggered_by = [aws_iam_role.lambda.id]
  }
}

resource "aws_cloudwatch_log_group" "handler" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${module.common.aws_region}:${module.common.aws_account_id}:${data.terraform_remote_state.routing.outputs.api_gateway_id}/*"
}
