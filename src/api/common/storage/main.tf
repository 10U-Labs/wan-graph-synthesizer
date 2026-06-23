# The single store for the whole product. Layout (S3 key prefixes):
#   source/    -- git-authored inputs pushed via the API (carriers/csps/customers)
#   builds/    -- per-create working artifacts (lifecycle-expired)
#   carriers/  csps/  substrate/  customers/  -- published graph JSON the read
#                                                endpoints serve
# Builds write here; every read endpoint serves from here.

resource "aws_s3_bucket" "store" {
  bucket = "wan-graph-synthesizer-store-us-east-2"
}

resource "aws_s3_bucket_public_access_block" "store" {
  bucket                  = aws_s3_bucket.store.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "store" {
  bucket = aws_s3_bucket.store.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Per-create working artifacts under builds/ are disposable: expire them so the
# bucket does not accumulate intermediate graph snapshots.
resource "aws_s3_bucket_lifecycle_configuration" "store" {
  bucket = aws_s3_bucket.store.id

  rule {
    id     = "expire-build-artifacts"
    status = "Enabled"
    filter {
      prefix = "builds/"
    }
    expiration {
      days = 14
    }
  }
}
