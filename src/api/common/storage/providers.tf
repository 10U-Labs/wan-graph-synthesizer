provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      ManagedBy  = "OpenTofu"
      Project    = "wan-graph-designer"
      Repository = "10U-Labs/wan-graph-designer"
      Stack      = "common/storage"
    }
  }
}
