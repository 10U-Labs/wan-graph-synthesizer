from __future__ import annotations

from pathlib import Path

import pytest

import test_terraform_config
from test_terraform_config import common_outputs


def test_the_file_read_is_the_shared_common_module(
        tf_document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_terraform_config, "COMMON_OUTPUTS_FILE", tf_document)
    assert common_outputs()["aws_region"] == "eu-west-1"


def test_every_output_that_file_declares_is_offered(
        tf_document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_terraform_config, "COMMON_OUTPUTS_FILE", tf_document)
    assert sorted(common_outputs()) == ["aws_region", "lambda_handler_names"]
