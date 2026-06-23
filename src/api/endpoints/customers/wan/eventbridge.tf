# Spot-interruption recovery. ECS emits a "Task State Change" event when our
# Fargate task stops; on a Spot reclaim the dispatching Lambda (same function)
# relaunches the build for that customer up to a cap. Keeps the cost of Spot
# without leaving an interrupted WAN stuck "building".

resource "aws_cloudwatch_event_rule" "task_stopped" {
  name        = "wan-graph-synthesizer-task-stopped"
  description = "Synthesizer Fargate task stopped; recover Spot interruptions"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.this.arn]
      lastStatus = ["STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "task_stopped_lambda" {
  rule      = aws_cloudwatch_event_rule.task_stopped.name
  target_id = "wan-lambda"
  arn       = aws_lambda_function.handler.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.task_stopped.arn
}
