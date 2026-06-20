output "api_gateway_id" {
  description = "REST API id (consumed by 10ulabs.com's CloudFront origin)."
  value       = aws_api_gateway_rest_api.api.id
}

output "api_gateway_execute_domain" {
  description = "execute-api origin domain for 10ulabs.com's CloudFront origin."
  value       = "${aws_api_gateway_rest_api.api.id}.execute-api.us-east-2.amazonaws.com"
}

output "stage_name" {
  description = "Deployed stage; CloudFront's origin_path is /prod."
  value       = aws_api_gateway_stage.prod.stage_name
}
