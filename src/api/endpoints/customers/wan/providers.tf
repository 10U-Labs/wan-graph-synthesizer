provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      ManagedBy  = "OpenTofu"
      Project    = "wan-graph-synthesizer"
      Repository = "10U-Labs/wan-graph-synthesizer"
      Stack      = "endpoints/customers/wan"
    }
  }
}

data "terraform_remote_state" "storage" {
  backend = "s3"
  config = {
    bucket = "10ulabs-terraform-state-us-east-2"
    key    = "wan-graph-synthesizer/common/storage/terraform.tfstate"
    region = "us-east-2"
  }
}
