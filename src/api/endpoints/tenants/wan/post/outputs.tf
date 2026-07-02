output "synthesizer_function_arn" {
  description = "ARN of the WAN synthesizer Lambda."
  value       = aws_lambda_function.synthesizer.arn
}

output "synthesizer_function_name" {
  description = "Name of the WAN synthesizer Lambda."
  value       = aws_lambda_function.synthesizer.function_name
}
