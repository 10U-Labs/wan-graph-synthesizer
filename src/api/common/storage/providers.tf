provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      ManagedBy  = "OpenTofu"
      Project    = "wan-synthesizer"
      Repository = "10U-Labs/wan-synthesizer"
      Stack      = "common/storage"
    }
  }
}
