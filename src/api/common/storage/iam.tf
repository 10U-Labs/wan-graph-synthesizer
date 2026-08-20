# The prune handler's role. It is the one role in the product that may delete from the
# store, which is the whole of what the endpoint does, so the permission is written here
# rather than added to a role that already reads and writes: an endpoint that only ever
# replaces a key it names has no business holding s3:DeleteObject.

resource "aws_iam_role" "prune" {
  name = local.prune_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "prune_basic" {
  role       = aws_iam_role.prune.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "prune_store_list_delete" {
  name = "StoreListDelete"
  role = aws_iam_role.prune.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.store.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.store.arn]
      }
    ]
  })
}
