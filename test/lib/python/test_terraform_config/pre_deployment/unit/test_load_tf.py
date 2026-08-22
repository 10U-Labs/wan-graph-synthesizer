from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from test_terraform_config import load_tf


def test_the_kinds_of_block_found_are_the_ones_the_file_declares(tf_document: Path) -> None:
    assert sorted(load_tf(tf_document)) == ["output", "resource"]


def test_an_output_keeps_the_value_it_was_declared_with(tf_document: Path) -> None:
    outputs = cast(list[dict[str, Any]], load_tf(tf_document)["output"])
    assert outputs[0]["aws_region"]["value"] == "eu-west-1"


def test_a_resource_keeps_the_body_it_was_declared_with(tf_document: Path) -> None:
    resources = cast(list[dict[str, Any]], load_tf(tf_document)["resource"])
    assert resources[0]["aws_s3_bucket"]["store"]["bucket"] == "the-document-store"
