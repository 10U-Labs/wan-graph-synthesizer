"""Unit tests for asking whether one address is among the ones a stack tracks.

Tracked and untracked are the two halves of the state question: a resource that exists and
is tracked is the deployment's own, and one that exists and is not is something the
deployment is about to collide with. This is the half that answers about tracking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import test_terraform_drift
from test_terraform_drift import is_resource_in_state

_STACK = Path("src/api/endpoints/carriers")


def _tracking(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    """Have the stack track *addresses* and nothing else."""
    monkeypatch.setattr(test_terraform_drift, "get_state_resources", lambda _dir: list(addresses))


def test_an_address_the_stack_tracks_is_reported_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resource in state is the deployment's own, and nothing to report."""
    _tracking(monkeypatch, "aws_s3_bucket.store", "aws_lambda_function.carriers")
    assert is_resource_in_state(_STACK, "aws_s3_bucket.store") is True


def test_an_address_the_stack_does_not_track_is_reported_untracked(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Untracked is the answer the state layer is looking for, so absence has to be plain."""
    _tracking(monkeypatch, "aws_lambda_function.carriers")
    assert is_resource_in_state(_STACK, "aws_s3_bucket.store") is False


def test_an_address_matched_in_part_is_not_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Addresses are compared whole; a prefix of one names a different resource."""
    _tracking(monkeypatch, "aws_s3_bucket.store_logs")
    assert is_resource_in_state(_STACK, "aws_s3_bucket.store") is False


def test_a_stack_tracking_nothing_tracks_this_either(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold state answers no to every address rather than failing the question."""
    _tracking(monkeypatch)
    assert is_resource_in_state(_STACK, "aws_s3_bucket.store") is False
