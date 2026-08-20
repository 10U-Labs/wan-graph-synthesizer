# The single store for the whole product, and the one endpoint that deletes from it.
# Layout (S3 key prefixes):
#   source/    -- git-authored inputs pushed via the API (carriers/providers/tenants)
#   builds/    -- per-create working artifacts (lifecycle-expired)
#   carriers/  providers/  tenants/  -- published graph JSON the read endpoints serve
# Builds write here; every read endpoint serves from here. Renaming a collection leaves
# the old key where it was, so POST /wan-synthesizer/store/prune takes out everything
# stored under a name the product no longer writes (GitHub issue #102); its handler is
# below, and it is the only thing in the product holding s3:DeleteObject on this bucket.
# The store holds one copy of each key: versioning is suspended below, so an
# overwrite replaces what was there rather than stacking another copy behind it.

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

# Two rules, both needed. Per-create working artifacts under builds/ are
# disposable: expire them so the bucket does not accumulate intermediate graph
# snapshots. And a delete that names no version id writes a delete marker over
# the key instead of removing it, so the second rule takes the marker away once
# nothing is left underneath it -- without it a deleted key stays in the bucket
# forever. The two cannot be one rule: S3 rejects an expiration that sets
# expired_object_delete_marker alongside days or date.
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
  prune_function_name = module.common.lambda_handler_names.prune
  prune_role_name     = "wan-synthesizer-prune-lambda"
}

# The gateway is read for its id alone, to say which API may invoke the handler. Nothing in
# routing reads this stack back: it builds every integration ARN from the deterministic
# function names in lib/opentofu/common, so the two stacks deploy in either order.
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
  function_name    = local.prune_function_name
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
  name              = "/aws/lambda/${local.prune_function_name}"
  retention_in_days = 7
}

resource "aws_lambda_permission" "prune_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.prune.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${module.common.aws_region}:${module.common.aws_account_id}:${data.terraform_remote_state.routing.outputs.api_gateway_id}/*"
}
