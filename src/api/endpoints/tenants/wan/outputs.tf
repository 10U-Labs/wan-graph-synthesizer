output "lambda_function_arn" {
  description = "ARN of the wan dispatching Lambda."
  value       = aws_lambda_function.handler.arn
}

output "lambda_function_name" {
  description = "Name of the wan dispatching Lambda."
  value       = aws_lambda_function.handler.function_name
}

output "ecr_repository_url" {
  description = "ECR repo the build_image workflow pushes the synthesizer image to."
  value       = aws_ecr_repository.synthesizer.repository_url
}

output "cluster_arn" {
  description = "ECS cluster the create task runs on."
  value       = aws_ecs_cluster.this.arn
}

output "task_definition_arn" {
  description = "Fargate task definition for the WAN-create synthesizer."
  value       = aws_ecs_task_definition.synthesizer.arn
}

output "subnet_id" {
  description = "Public subnet the create task launches in."
  value       = aws_subnet.public.id
}

output "security_group_id" {
  description = "Security group (egress-only) for the create task."
  value       = aws_security_group.task.id
}

output "task_role_arn" {
  description = "The synthesizer task role (read inputs, write graph JSON)."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "The Fargate execution role (image pull + logs)."
  value       = aws_iam_role.execution.arn
}
