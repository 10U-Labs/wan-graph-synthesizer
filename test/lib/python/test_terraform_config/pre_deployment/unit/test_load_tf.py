"""Unit tests for reading an OpenTofu file into a document the other helpers walk.

Every value twenty-nine test files take from the declaration arrives through this read:
the account, the region, the state bucket and the Lambda function names. It is the one
place in the module that opens a file, and everything after it works on what it returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from test_terraform_config import load_tf


def test_the_kinds_of_block_found_are_the_ones_the_file_declares(tf_document: Path) -> None:
    """A read names the kinds of block it found, so a caller knows what it may ask for."""
    assert sorted(load_tf(tf_document)) == ["output", "resource"]


def test_an_output_keeps_the_value_it_was_declared_with(tf_document: Path) -> None:
    """The parse is literal: what the file says is what the document holds."""
    outputs = cast("list[dict[str, Any]]", load_tf(tf_document)["output"])
    assert outputs[0]["aws_region"]["value"] == "eu-west-1"


def test_a_resource_keeps_the_body_it_was_declared_with(tf_document: Path) -> None:
    """Resource bodies survive the read too, since a drift check reads names out of them."""
    resources = cast("list[dict[str, Any]]", load_tf(tf_document)["resource"])
    assert resources[0]["aws_s3_bucket"]["store"]["bucket"] == "the-document-store"
