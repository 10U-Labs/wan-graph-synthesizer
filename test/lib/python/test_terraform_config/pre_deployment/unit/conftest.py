"""A small OpenTofu document written for the parser tests to read.

The parser is asked for the literal value of an ``output`` block and for the body of a
``resource`` block, so what it needs is a file declaring both, small enough that the
expected answer is visible beside the assertion. It is written here rather than in each
test file so that the shape every test reads is stated once.

The values are deliberately not this repository's: a parser test that reads the real
``lib/opentofu/common/outputs.tf`` passes just as well when the parser returns a value it
invented, because the answer it invented is the one the test was written from. Holding
the module against the real file is a contract, and it is asked one tier up.
"""

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
    """A ``.tf`` file declaring three outputs and one resource."""
    path = tmp_path / "outputs.tf"
    path.write_text(_DOCUMENT, encoding="utf-8")
    return path
