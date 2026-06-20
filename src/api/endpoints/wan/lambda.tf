# The dispatching Lambda: POST starts a Fargate create (ecs:RunTask), GET reports
# the customer's WAN status from the store. It lives in the wan stack so it can
# reference the cluster, task definition, subnet, and security group directly.

data "terraform_remote_state" "routing" {
  backend = "s3"

  config = {
    bucket = "10ulabs-terraform-state-us-east-2"
    key    = "wan-graph-designer/common/routing/terraform.tfstate"
    region = "us-east-2"
  }
}

data "archive_file" "handler" {
  type        = "zip"
  source_file = "${path.module}/lambdas/handler.py"
  output_path = "${path.module}/.terraform/lambda_packages/handler.zip"
}

resource "aws_lambda_function" "handler" {
  filename         = data.archive_file.handler.output_path
  function_name    = module.common.lambda_handler_names.wan
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.handler.output_base64sha256
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 10
  memory_size      = 128
  description      = "WAN create endpoint: start the Fargate optimize, report status."

  environment {
    variables = {
      STORE_BUCKET        = local.store_bucket
      CLUSTER_ARN         = aws_ecs_cluster.this.arn
      TASK_DEFINITION_ARN = aws_ecs_task_definition.optimizer.arn
      SUBNET_ID           = aws_subnet.public.id
      SECURITY_GROUP_ID   = aws_security_group.task.id
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
  name              = "/aws/lambda/${module.common.lambda_handler_names.wan}"
  retention_in_days = 7
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${module.common.aws_region}:${module.common.aws_account_id}:${data.terraform_remote_state.routing.outputs.api_gateway_id}/*"
}
