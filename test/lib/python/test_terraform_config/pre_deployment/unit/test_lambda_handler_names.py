from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import lambda_handler_names


def _declared(monkeypatch: pytest.MonkeyPatch, outputs: dict[str, Any]) -> None:
    monkeypatch.setattr(test_terraform_config, "common_outputs", lambda: outputs)


def test_the_names_declared_are_the_names_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"lambda_handler_names": {"carriers": "wan-graph-carriers"}})
    assert lambda_handler_names() == {"carriers": "wan-graph-carriers"}


def test_a_name_declared_as_a_number_is_offered_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"lambda_handler_names": {"carriers": 42}})
    assert lambda_handler_names() == {"carriers": "42"}


def test_a_common_module_declaring_no_such_output_offers_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"aws_region": "eu-west-1"})
    assert lambda_handler_names() == {}


def test_an_output_that_is_not_a_mapping_offers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, {"lambda_handler_names": "wan-graph-carriers"})
    assert lambda_handler_names() == {}
