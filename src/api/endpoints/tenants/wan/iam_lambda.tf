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
