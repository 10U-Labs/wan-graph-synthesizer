output "lambda_function_arn" {
  description = "ARN of the wan dispatching Lambda."
  value       = aws_lambda_function.handler.arn
}

output "lambda_function_name" {
  description = "Name of the wan dispatching Lambda."
  value       = aws_lambda_function.handler.function_name
}

output "worker_function_arn" {
  description = "ARN of the WAN synthesize worker Lambda."
  value       = aws_lambda_function.worker.arn
}

output "worker_function_name" {
  description = "Name of the WAN synthesize worker Lambda."
  value       = aws_lambda_function.worker.function_name
}
