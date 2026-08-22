from __future__ import annotations

from pathlib import Path

import pytest

_DOCUMENT = """
output "aws_region" {
  description = "The region the stack in this document deploys into."
  value       = "eu-west-1"
}

output "lambda_handler_names" {
  description = "One function name per resource."
  value = {
    carriers = "document-carriers"
    tenants  = "document-tenants"
  }
}

output "described_but_unset" {
  description = "An output carrying no value at all."
}

resource "aws_s3_bucket" "store" {
  bucket = "the-document-store"
}
"""


@pytest.fixture
def tf_document(tmp_path: Path) -> Path:
    path = tmp_path / "outputs.tf"
    path.write_text(_DOCUMENT, encoding="utf-8")
    return path
