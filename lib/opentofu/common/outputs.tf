output "aws_account_id" {
  description = "The AWS account every stack deploys into."
  value       = "781581267945"
}

output "aws_region" {
  description = "The region every stack deploys into."
  value       = "us-east-2"
}

output "state_bucket" {
  description = "The shared OpenTofu state bucket."
  value       = "10ulabs-terraform-state-us-east-2"
}


output "lambda_handler_names" {
  description = "Deterministic Lambda function names, one per REST resource."
  value = {
    carriers  = "wan-synthesizer-carriers"
    providers = "wan-synthesizer-providers"
    tenants   = "wan-synthesizer-tenants"
    merge     = "wan-synthesizer-merge"
    prune     = "wan-synthesizer-prune"
    wan       = "wan-synthesizer-wan"
  }
}
