# Shared constants for every stack (mirrors 10ulabs.com's lib/terraform/common).
# A module with no resources -- just the account/region/naming every endpoint and
# the routing gateway reference, so a name is defined in exactly one place.

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

output "github_repo_full" {
  description = "owner/name of this repository (for resource tags)."
  value       = "10U-Labs/wan-graph-synthesizer"
}

output "lambda_handler_names" {
  description = "Deterministic Lambda function names, one per REST resource."
  value = {
    carriers  = "wan-synthesizer-carriers"
    providers = "wan-synthesizer-providers"
    tenants   = "wan-synthesizer-tenants"
    merge     = "wan-synthesizer-merge"
    wan       = "wan-synthesizer-wan"
  }
}
