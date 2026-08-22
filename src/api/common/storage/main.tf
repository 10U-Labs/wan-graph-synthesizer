resource "aws_s3_bucket" "store" {
  bucket = "wan-synthesizer-store-us-east-2"
}

resource "aws_s3_bucket_public_access_block" "store" {
  bucket                  = aws_s3_bucket.store.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "store" {
  bucket = aws_s3_bucket.store.id
  versioning_configuration {
    status = "Suspended"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "store" {
  bucket = aws_s3_bucket.store.id

  rule {
    id     = "expire-build-artifacts"
    status = "Enabled"
    filter {
      prefix = "builds/"
    }
    expiration {
      days = 14
    }
  }

  rule {
    id     = "expire-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
}


module "common" {
  source = "../../../../lib/opentofu/common"
}

locals {
  function_name = module.common.lambda_handler_names.prune
  role_name     = "wan-synthesizer-prune-lambda"
}

data "terraform_remote_state" "routing" {
  backend = "s3"

  config = {
    bucket = module.common.state_bucket
    key    = "wan-synthesizer/common/routing/terraform.tfstate"
    region = module.common.aws_region
  }
}

data "archive_file" "prune" {
  type        = "zip"
  source_file = "${path.module}/lambdas/handler.py"
  output_path = "${path.module}/.terraform/lambda_packages/handler.zip"
}

resource "aws_lambda_function" "prune" {
  filename         = data.archive_file.prune.output_path
  function_name    = local.function_name
  role             = aws_iam_role.prune.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.prune.output_base64sha256
  runtime          = "python3.13"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256
  description      = "Store prune endpoint: delete the objects no endpoint serves any more."

  environment {
    variables = {
      STORE_BUCKET = aws_s3_bucket.store.id
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.prune.name
  }

  lifecycle {
    replace_triggered_by = [aws_iam_role.prune.id]
  }
}

resource "aws_cloudwatch_log_group" "prune" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7
}

resource "aws_lambda_permission" "prune_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.prune.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${module.common.aws_region}:${module.common.aws_account_id}:${data.terraform_remote_state.routing.outputs.api_gateway_id}/*"
}
