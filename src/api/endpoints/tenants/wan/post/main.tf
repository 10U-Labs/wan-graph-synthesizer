locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}

data "archive_file" "synthesizer" {
  type        = "zip"
  source_dir  = "${path.module}/lambdas"
  output_path = "${path.module}/.terraform/lambda_packages/synthesizer.zip"
}

data "archive_file" "solver_layer" {
  type        = "zip"
  source_dir  = "${path.module}/.terraform/solver_layer"
  output_path = "${path.module}/.terraform/lambda_packages/solver_layer.zip"
}

resource "aws_lambda_layer_version" "solver" {
  filename                 = data.archive_file.solver_layer.output_path
  source_code_hash         = data.archive_file.solver_layer.output_base64sha256
  layer_name               = "wan-synthesizer-solver"
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["arm64"]
  description              = "highspy 1.15.1 and numpy 2.3.5: the solver the synthesizer's backbone search calls."
}

resource "aws_iam_role" "synthesizer" {
  name = "wan-synthesizer-synthesizer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "synthesizer_basic" {
  role       = aws_iam_role.synthesizer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "synthesizer_s3" {
  name = "store-access"
  role = aws_iam_role.synthesizer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        data.terraform_remote_state.storage.outputs.bucket_arn,
        "${data.terraform_remote_state.storage.outputs.bucket_arn}/*",
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "synthesizer" {
  name              = "/aws/lambda/${module.common.lambda_handler_names.wan}-synthesizer"
  retention_in_days = 14
}

resource "aws_lambda_function" "synthesizer" {
  filename         = data.archive_file.synthesizer.output_path
  function_name    = "${module.common.lambda_handler_names.wan}-synthesizer"
  role             = aws_iam_role.synthesizer.arn
  handler          = "synthesizer.handler.lambda_handler"
  source_code_hash = data.archive_file.synthesizer.output_base64sha256
  runtime          = "python3.13"
  architectures    = ["arm64"]
  layers           = [aws_lambda_layer_version.solver.arn]
  timeout     = 900
  memory_size = 8192
  description = "WAN synthesizer: build the tenant's WAN and write it to the store."

  environment {
    variables = {
      STORE_BUCKET = local.store_bucket
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.synthesizer.name
  }

  lifecycle {
    replace_triggered_by = [aws_iam_role.synthesizer.id]
  }
}

resource "aws_iam_role" "failure_handler" {
  name = "wan-synthesizer-failure-handler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "failure_handler_basic" {
  role       = aws_iam_role.failure_handler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "failure_handler_s3" {
  name = "store-write"
  role = aws_iam_role.failure_handler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = ["${data.terraform_remote_state.storage.outputs.bucket_arn}/*"]
    }]
  })
}

resource "aws_cloudwatch_log_group" "failure_handler" {
  name              = "/aws/lambda/${module.common.lambda_handler_names.wan}-failure-handler"
  retention_in_days = 14
}

resource "aws_lambda_function" "failure_handler" {
  filename         = data.archive_file.synthesizer.output_path
  function_name    = "${module.common.lambda_handler_names.wan}-failure-handler"
  role             = aws_iam_role.failure_handler.arn
  handler          = "synthesizer.failure_handler.lambda_handler"
  source_code_hash = data.archive_file.synthesizer.output_base64sha256
  runtime          = "python3.13"
  architectures    = ["arm64"]
  layers           = [aws_lambda_layer_version.solver.arn]
  timeout     = 30
  memory_size = 128
  description = "WAN failure handler: record the timeout status when AWS kills the synthesizer."

  environment {
    variables = {
      STORE_BUCKET = local.store_bucket
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.failure_handler.name
  }

  lifecycle {
    replace_triggered_by = [aws_iam_role.failure_handler.id]
  }
}

resource "aws_iam_role_policy" "synthesizer_destination" {
  name = "on-failure-destination"
  role = aws_iam_role.synthesizer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.failure_handler.arn]
    }]
  })
}

resource "aws_lambda_function_event_invoke_config" "synthesizer" {
  function_name          = aws_lambda_function.synthesizer.function_name
  maximum_retry_attempts = 0

  destination_config {
    on_failure {
      destination = aws_lambda_function.failure_handler.arn
    }
  }
}
