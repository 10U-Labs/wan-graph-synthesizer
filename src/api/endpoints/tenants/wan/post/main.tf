# The synthesizer: a zip-packaged Lambda that runs the whole pipeline
# (dual-home -> overrides -> synthesize -> finalize) in one invocation and writes the
# tenant's WAN JSON to the S3 store, or records why none was possible. The dispatching Lambda
# (in the sibling `../` stack) async-invokes it on a WAN create (POST /tenants/{t}/wan),
# the only build trigger, referencing it by its deterministic derived name.
# A build is single-threaded, finishes in seconds with a few-GB working set, and needs
# nothing beyond stdlib, boto3 and the solver in aws_lambda_layer_version.solver, so it
# fits Lambda's 15-minute / 10 GB envelope.
# This `post/` stack (owned by the *_post.yml workflow) is self-contained: its lambda code
# lives under `./lambdas/`.

locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}

# Package this stack's lambda code (./lambdas/synthesizer/, handler + engine) into a zip,
# preserving the synthesizer/ prefix so its `from synthesizer.X import ...` resolve.
data "archive_file" "synthesizer" {
  type        = "zip"
  source_dir  = "${path.module}/lambdas"
  output_path = "${path.module}/.terraform/lambda_packages/synthesizer.zip"
}

# The solver the backbone search runs on, shipped as a Lambda layer instead of inside the
# function's own zip. `data "archive_file" "synthesizer"` above zips the whole of
# src/api/endpoints/tenants/wan/post/lambdas, so a wheel unpacked there would land under
# src/, and pylint-source, mypy-source and copy-paste-source read everything they find
# under src/ -- they would report on third-party code nobody here wrote and the workflow
# would go red. This layer is what keeps that code out of src/. It holds two pinned wheels:
# highspy 1.15.1, the HiGHS solver that synthesizer/linear_program.py calls to round the
# linear-programming relaxation, and numpy 2.3.5, which highspy needs. The workflow fetches
# both by URL, checks their sha256 and unpacks them into
# ${path.module}/.terraform/solver_layer/python/ before tofu reads this data source.
# Both aws_lambda_function.synthesizer and aws_lambda_function.failure_handler attach it.
# They already share one deployment package, and attaching the layer to only one of them
# would start them drifting apart.
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

# The synthesizer's own role: read inputs + write published/working graph JSON.
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
  # The build is single-threaded and finishes in seconds with a few-GB working set;
  # 8192 MB matches the prior 8 GB Fargate task so enumeration_limit is unchanged, and
  # 900s (the Lambda max) is ample headroom over a ~5s build.
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

# The failure handler: a tiny Lambda wired to the synthesizer's async on_failure
# destination. AWS delivers a failed synthesizer invocation here only when it did NOT
# return -- a 900s timeout, an out-of-memory kill, or an unhandled crash -- because those
# kill the sandbox before the synthesizer's `except` can record anything at all, leaving
# the WAN stuck on "synthesizing" forever. It records "timeout", which is a different
# ending from the "fail" the synthesizer writes when it decides no valid WAN is possible:
# one asks the operator to change the tenant's config, the other to try again. It reuses the synthesizer's deployment package but is its
# own function, entered at a different handler and running as its own write-only role.
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

# Write-only: the failure handler records a status marker and nothing else -- it never
# reads inputs nor invokes anything (least privilege).
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
  # It writes a single S3 object; the default envelope is ample.
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

# Sending to a Lambda on_failure destination requires the source function's execution role
# to be allowed to invoke the destination.
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

# Pin async retries to zero and route a failed invocation to the failure handler. A
# timeout kill can't be caught in-process, so retrying would only re-stamp "synthesizing"
# without ever reaching a terminal status; the destination records "timeout" instead.
resource "aws_lambda_function_event_invoke_config" "synthesizer" {
  function_name          = aws_lambda_function.synthesizer.function_name
  maximum_retry_attempts = 0

  destination_config {
    on_failure {
      destination = aws_lambda_function.failure_handler.arn
    }
  }
}
