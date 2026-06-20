output "lambda_function_arn" {
  description = "ARN of the customers Lambda."
  value       = aws_lambda_function.handler.arn
}

output "lambda_function_name" {
  description = "Name of the customers Lambda."
  value       = aws_lambda_function.handler.function_name
}
