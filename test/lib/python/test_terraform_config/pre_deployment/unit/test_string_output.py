"""Unit tests for the string outputs the region and the state bucket are taken from.

Both are read once, at import, and every client the suite builds is built for whatever
they hold. The read falls back to a literal when the declaration does not answer, and a
fallback that wins silently is the failure this covers: the suite goes on measuring a
region nobody deploys to, and every resource it asks about is reported absent.
"""

from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import _string_output


def _declared(monkeypatch: pytest.MonkeyPatch, outputs: dict[str, Any]) -> None:
    """Have the shared common module declare ``outputs`` and nothing else."""
    monkeypatch.setattr(test_terraform_config, "common_outputs", lambda: outputs)


def test_a_declared_string_is_the_value_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """The declaration wins over the fallback whenever it answers."""
    _declared(monkeypatch, {"aws_region": "eu-west-1"})
    assert _string_output("aws_region", "us-east-2") == "eu-west-1"


def test_an_output_that_is_not_declared_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing declaration leaves the suite something to run with rather than an import error."""
    _declared(monkeypatch, {})
    assert _string_output("aws_region", "us-east-2") == "us-east-2"


def test_an_output_declared_as_something_other_than_text_falls_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A region is passed to a client as text, so a map declared under that name is no answer."""
    _declared(monkeypatch, {"aws_region": {"primary": "eu-west-1"}})
    assert _string_output("aws_region", "us-east-2") == "us-east-2"
