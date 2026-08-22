from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import _string_output


def _declared(monkeypatch: pytest.MonkeyPatch, outputs: dict[str, Any]) -> None:
    monkeypatch.setattr(test_terraform_config, "common_outputs", lambda: outputs)


def test_a_declared_string_is_the_value_used(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"aws_region": "eu-west-1"})
    assert _string_output("aws_region", "us-east-2") == "eu-west-1"


def test_an_output_that_is_not_declared_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {})
    assert _string_output("aws_region", "us-east-2") == "us-east-2"


def test_an_output_declared_as_something_other_than_text_falls_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"aws_region": {"primary": "eu-west-1"}})
    assert _string_output("aws_region", "us-east-2") == "us-east-2"
