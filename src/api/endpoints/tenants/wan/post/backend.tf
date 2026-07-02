terraform {
  backend "s3" {
    bucket = "10ulabs-terraform-state-us-east-2"
    # The stack directory was renamed synthesizer/ -> post/, but the state key is kept so
    # `init` finds the existing state; renaming it would orphan state and try to re-create
    # the already-live Lambda/role/log group.
    key          = "wan-graph-synthesizer/endpoints/tenants/wan/synthesizer/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }

  required_version = ">= 1.6"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
