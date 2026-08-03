"""Unit tests for the read of the shared common module every other value comes from.

One file declares the account, the region, the state bucket and the Lambda function names
for every stack, and this is the call that opens it. Twenty-nine test files reach the
declaration through here, so the file it opens is the whole of what they are asserting
against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import test_terraform_config
from test_terraform_config import common_outputs


def test_the_file_read_is_the_shared_common_module(
        tf_document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The call takes its path from the module constant and opens nothing else."""
    monkeypatch.setattr(test_terraform_config, "COMMON_OUTPUTS_FILE", tf_document)
    assert common_outputs()["aws_region"] == "eu-west-1"


def test_every_output_that_file_declares_is_offered(
        tf_document: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller sees all of the shared values, not the ones this module has a name for."""
    monkeypatch.setattr(test_terraform_config, "COMMON_OUTPUTS_FILE", tf_document)
    assert sorted(common_outputs()) == ["aws_region", "lambda_handler_names"]
