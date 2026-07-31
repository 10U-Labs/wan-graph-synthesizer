resource "aws_iam_role" "lambda" {
  name = "wan-graph-synthesizer-wan-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Read/write status markers and async-invoke the synthesizer. The synthesizer lives in
# its own stack, so the invoke target is its deterministic derived ARN (from the shared
# common module) rather than a cross-stack resource reference.
resource "aws_iam_role_policy" "dispatch" {
  name = "Dispatch"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${data.terraform_remote_state.storage.outputs.bucket_arn}/*"]
      },
      # Listing is what makes a missing status marker a not-found rather than a crash. S3
      # answers a read of an absent key with AccessDenied unless the caller may also list
      # the bucket, and only then with NoSuchKey -- so without this the handler's NoSuchKey
      # branch never runs and a GET for a tenant that has never been built raises instead
      # of returning 404. The grant is on the bucket itself, since that is what a listing
      # names; the read and write above are on its contents.
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [data.terraform_remote_state.storage.outputs.bucket_arn]
      },
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          "arn:aws:lambda:${module.common.aws_region}:${module.common.aws_account_id}:function:${module.common.lambda_handler_names.wan}-synthesizer"
        ]
      }
    ]
  })
}
