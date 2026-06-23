provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      ManagedBy  = "OpenTofu"
      Project    = "wan-graph-synthesizer"
      Repository = "10U-Labs/wan-graph-synthesizer"
      Stack      = "common/storage"
    }
  }
}
