# The single store for the whole product. Layout (S3 key prefixes):
#   source/    -- git-authored inputs pushed via the API (carriers/providers/tenants)
#   builds/    -- per-create working artifacts (lifecycle-expired)
#   carriers/  providers/  tenants/  -- published graph JSON the read endpoints serve
# Builds write here; every read endpoint serves from here.
# The store holds one copy of each key: versioning is suspended below, so an
# overwrite replaces what was there rather than stacking another copy behind it.

resource "aws_s3_bucket" "store" {
  bucket = "wan-synthesizer-store-us-east-2"
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
    status = "Suspended"
  }
}

# Two rules, both needed. Per-create working artifacts under builds/ are
# disposable: expire them so the bucket does not accumulate intermediate graph
# snapshots. And a delete that names no version id writes a delete marker over
# the key instead of removing it, so the second rule takes the marker away once
# nothing is left underneath it -- without it a deleted key stays in the bucket
# forever. The two cannot be one rule: S3 rejects an expiration that sets
# expired_object_delete_marker alongside days or date.
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

  rule {
    id     = "expire-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
    }
  }
}
