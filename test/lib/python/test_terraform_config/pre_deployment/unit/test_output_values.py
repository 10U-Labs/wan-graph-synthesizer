"""Unit tests for reducing a file's ``output`` blocks to the values they declare.

This is where a declaration becomes a value a test can assert against, and where a value
can go missing without anything saying so: an output the reduction drops is simply not in
the mapping, and the caller that reads it either falls back to a literal of its own or
fails naming the key. Both readings are wrong about the same thing, which is that the
declaration was never read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import output_values


def _document(monkeypatch: pytest.MonkeyPatch, parsed: dict[str, Any]) -> None:
    """Have the read hand back ``parsed``, for shapes a real file cannot be written to give."""
    monkeypatch.setattr(test_terraform_config, "load_tf", lambda _path: parsed)


def test_a_string_output_is_reduced_to_its_string(tf_document: Path) -> None:
    """The region a test builds a client for is a string in the file and a string here."""
    assert output_values(tf_document)["aws_region"] == "eu-west-1"


def test_a_map_output_is_reduced_to_its_mapping(tf_document: Path) -> None:
    """The Lambda function names are declared as one map, and stay one mapping."""
    assert output_values(tf_document)["lambda_handler_names"] == {
        "carriers": "document-carriers",
        "tenants": "document-tenants",
    }


def test_every_output_declaring_a_value_is_reduced(tf_document: Path) -> None:
    """Nothing declared with a value is dropped on the way through."""
    assert sorted(output_values(tf_document)) == ["aws_region", "lambda_handler_names"]


def test_an_output_declaring_no_value_is_left_out(tf_document: Path) -> None:
    """A block carrying only a description has no value to offer, and none is invented."""
    assert "described_but_unset" not in output_values(tf_document)


def test_a_file_declaring_no_outputs_yields_nothing(tmp_path: Path) -> None:
    """A file of resources alone is empty here rather than an error."""
    path = tmp_path / "main.tf"
    path.write_text('resource "aws_s3_bucket" "store" {\n  bucket = "b"\n}\n', encoding="utf-8")
    assert output_values(path) == {}


def test_a_document_whose_outputs_are_not_a_list_yields_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is reduced from a document shaped unlike anything the parser emits."""
    _document(monkeypatch, {"output": {"aws_region": {"value": "eu-west-1"}}})
    assert output_values(tmp_path / "ignored.tf") == {}


def test_a_block_that_is_not_a_block_is_stepped_over(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One unreadable entry does not hide the outputs declared after it."""
    _document(monkeypatch, {"output": ["not a block", {"aws_region": {"value": "eu-west-1"}}]})
    assert output_values(tmp_path / "ignored.tf") == {"aws_region": "eu-west-1"}


def test_a_block_body_that_is_not_a_body_is_stepped_over(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A name carrying something other than a body declares no value to reduce."""
    _document(monkeypatch, {"output": [{"aws_region": "not a body"}]})
    assert output_values(tmp_path / "ignored.tf") == {}
