from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import output_values


def _document(monkeypatch: pytest.MonkeyPatch, parsed: dict[str, Any]) -> None:
    monkeypatch.setattr(test_terraform_config, "load_tf", lambda _path: parsed)


def test_a_string_output_is_reduced_to_its_string(tf_document: Path) -> None:
    assert output_values(tf_document)["aws_region"] == "eu-west-1"


def test_a_map_output_is_reduced_to_its_mapping(tf_document: Path) -> None:
    assert output_values(tf_document)["lambda_handler_names"] == {
        "carriers": "document-carriers",
        "tenants": "document-tenants",
    }


def test_every_output_declaring_a_value_is_reduced(tf_document: Path) -> None:
    assert sorted(output_values(tf_document)) == ["aws_region", "lambda_handler_names"]


def test_an_output_declaring_no_value_is_left_out(tf_document: Path) -> None:
    assert "described_but_unset" not in output_values(tf_document)


def test_a_file_declaring_no_outputs_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "aws_s3_bucket" "store" {\n  bucket = "b"\n}\n', encoding="utf-8")
    assert len(output_values(path)) == 0


def test_a_document_whose_outputs_are_not_a_list_yields_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _document(monkeypatch, {"output": {"aws_region": {"value": "eu-west-1"}}})
    assert len(output_values(tmp_path / "ignored.tf")) == 0


def test_a_block_that_is_not_a_block_is_stepped_over(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _document(monkeypatch, {"output": ["not a block", {"aws_region": {"value": "eu-west-1"}}]})
    assert output_values(tmp_path / "ignored.tf") == {"aws_region": "eu-west-1"}


def test_a_block_body_that_is_not_a_body_is_stepped_over(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _document(monkeypatch, {"output": [{"aws_region": "not a body"}]})
    assert len(output_values(tmp_path / "ignored.tf")) == 0
