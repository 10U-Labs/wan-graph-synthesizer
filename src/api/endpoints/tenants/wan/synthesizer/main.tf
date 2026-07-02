# The synthesizer: a zip-packaged Lambda that runs the whole pipeline
# (dual-home -> overrides -> synthesize -> finalize) in one invocation and writes the
# tenant's WAN JSON to the S3 store, or records a failed reason. The dispatching Lambda
# (in the sibling `../` stack) async-invokes it on a WAN create (POST /tenants/{t}/wan),
# the only build trigger, referencing it by its deterministic derived name.
# A build is single-threaded, finishes in seconds with a few-GB working set, and needs
# nothing beyond stdlib + boto3, so it fits Lambda's 15-minute / 10 GB envelope.

locals {
  store_bucket = data.terraform_remote_state.storage.outputs.bucket_name
}

# Package the synthesizer package (../lambdas/synthesizer/, handler + engine) into a zip,
# preserving the synthesizer/ prefix so its `from synthesizer.X import ...` resolve. The
# dispatcher (../lambdas/endpoint/handler.py) is excluded; it ships in its own stack's zip.
data "archive_file" "synthesizer" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas"
  excludes    = ["endpoint/handler.py"]
  output_path = "${path.module}/.terraform/lambda_packages/synthesizer.zip"
}

resource "aws_iam_role" "synthesizer" {
  name = "wan-graph-synthesizer-synthesizer"
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
