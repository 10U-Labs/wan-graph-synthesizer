"""Unit tests for the per-resource Lambda function names taken from the common module.

A post-deployment test asks the platform about a function by name, so the name it asks
under decides which function is inspected. A name that arrives empty fails the lookup and
names the function; a mapping that arrives empty skips the lookup and reports nothing at
all, which is the reading that costs more.
"""

from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import lambda_handler_names


def _declared(monkeypatch: pytest.MonkeyPatch, outputs: dict[str, Any]) -> None:
    """Have the shared common module declare ``outputs`` and nothing else."""
    monkeypatch.setattr(test_terraform_config, "common_outputs", lambda: outputs)


def test_the_names_declared_are_the_names_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each REST resource key keeps the function name the declaration gives it."""
    _declared(monkeypatch, {"lambda_handler_names": {"carriers": "wan-graph-carriers"}})
    assert lambda_handler_names() == {"carriers": "wan-graph-carriers"}


def test_a_name_declared_as_a_number_is_offered_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Callers pass these straight to the platform, which names functions in text."""
    _declared(monkeypatch, {"lambda_handler_names": {"carriers": 42}})
    assert lambda_handler_names() == {"carriers": "42"}


def test_a_common_module_declaring_no_such_output_offers_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An output that is not declared is empty here rather than an error at import."""
    _declared(monkeypatch, {"aws_region": "eu-west-1"})
    assert lambda_handler_names() == {}


def test_an_output_that_is_not_a_mapping_offers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A declaration of the wrong shape holds no names, whatever else it holds."""
    _declared(monkeypatch, {"lambda_handler_names": "wan-graph-carriers"})
    assert lambda_handler_names() == {}
