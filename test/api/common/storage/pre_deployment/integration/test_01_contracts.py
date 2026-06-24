"""Layer 1 (contracts): cross-file consistency within the storage stack.

These assert that the stack's published outputs match the resources it declares.
No AWS calls -- pure ``.tf`` parsing.
"""
from __future__ import annotations

from repo_utils import REPO_ROOT
from test_terraform_config import output_values

STORAGE_DIR = REPO_ROOT / "src" / "api" / "common" / "storage"


def test_outputs_declare_the_bucket_name_and_arn() -> None:
    """The stack publishes exactly the store bucket's name and ARN."""
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert set(outputs) == {"bucket_name", "bucket_arn"}


def test_bucket_name_output_references_the_declared_store() -> None:
    """The ``bucket_name`` output is wired to the declared store resource."""
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert "aws_s3_bucket.store" in str(outputs["bucket_name"])
