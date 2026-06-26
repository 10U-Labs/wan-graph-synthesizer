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

# Read/write status markers, launch the create task, and pass it its roles.
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
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = ["${aws_ecs_task_definition.synthesizer.arn_without_revision}:*"]
      },
      {
        # Tag the task on launch with Tenant/Attempt. TagResource applies to the
        # task resource (random id), not the task definition.
        Effect   = "Allow"
        Action   = ["ecs:TagResource"]
        Resource = ["arn:aws:ecs:${module.common.aws_region}:${module.common.aws_account_id}:task/${aws_ecs_cluster.this.name}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task.arn, aws_iam_role.execution.arn]
      },
      {
        # Read a stopped task's tags (Tenant/Attempt) to relaunch on Spot reclaim.
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks"]
        Resource = ["*"]
      },
      {
        # Schedule a delayed Spot relaunch when run_task can't place a task (no stopped
        # event fires for a placement shortfall). The schedule deletes itself after firing.
        Effect   = "Allow"
        Action   = ["scheduler:CreateSchedule"]
        Resource = ["arn:aws:scheduler:${module.common.aws_region}:${module.common.aws_account_id}:schedule/default/wan-retry-*"]
      },
      {
        # Hand the retry schedule the role it assumes to re-invoke this Lambda.
        Effect    = "Allow"
        Action    = ["iam:PassRole"]
        Resource  = [aws_iam_role.scheduler.arn]
        Condition = { StringEquals = { "iam:PassedToService" = "scheduler.amazonaws.com" } }
      }
    ]
  })
}

# The role EventBridge Scheduler assumes to re-invoke the wan Lambda for a delayed Spot
# retry. Its Lambda ARN is built from the known name (not the resource) to avoid a cycle:
# the Lambda's environment already references this role's ARN.
resource "aws_iam_role" "scheduler" {
  name = "wan-graph-synthesizer-wan-retry-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "InvokeWanHandler"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = ["arn:aws:lambda:${module.common.aws_region}:${module.common.aws_account_id}:function:${module.common.lambda_handler_names.wan}"]
    }]
  })
}
