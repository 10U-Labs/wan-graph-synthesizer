"""Unit tests for reading the resource addresses a stack currently tracks.

The state layer is skipped on a stack that has never been deployed, because a stack with
nothing tracked has nothing to compare against and would fail its first run on a condition
that cannot yet be true. This read is what that decision is made on, so an empty answer is
not a detail: it is the difference between a layer that runs and a layer that is skipped.

The state command is replaced here, since the answer under test is the reading of what it
printed rather than anything OpenTofu decides.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_terraform_drift import get_state_resources

_STACK = Path("src/api/endpoints/carriers")


def _listing(monkeypatch: pytest.MonkeyPatch, printed: str, returncode: int = 0) -> None:
    """Have ``tofu state list`` print *printed* and exit with *returncode*."""
    answer = subprocess.CompletedProcess(
        args=["tofu"], returncode=returncode, stdout=printed, stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: answer)


def test_each_address_printed_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """One address per line is what the command prints, and all of them are tracked."""
    _listing(monkeypatch, "aws_s3_bucket.store\naws_lambda_function.carriers\n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store", "aws_lambda_function.carriers"]


def test_the_spacing_around_an_address_is_not_part_of_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Addresses are compared exactly, so a trailing space would hide a tracked resource."""
    _listing(monkeypatch, "  aws_s3_bucket.store  \n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store"]


def test_a_blank_line_is_not_an_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty address would match nothing and count as something tracked all the same."""
    _listing(monkeypatch, "aws_s3_bucket.store\n\n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store"]


def test_a_stack_tracking_nothing_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold state is the ordinary case for a unit that has never been deployed."""
    _listing(monkeypatch, "")
    assert get_state_resources(_STACK) == []


def test_a_command_that_failed_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An uninitialised stack cannot be listed, and that is read as cold rather than as clean."""
    _listing(monkeypatch, "aws_s3_bucket.store\n", returncode=1)
    assert get_state_resources(_STACK) == []


def test_the_state_is_listed_in_the_stack_directory_it_was_given(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """State is per stack, so a listing taken anywhere else describes something else."""
    asked: list[Any] = []
    answer = subprocess.CompletedProcess(args=["tofu"], returncode=0, stdout="", stderr="")

    def run(_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Record where the listing was asked for and print nothing."""
        asked.append(kwargs["cwd"])
        return answer

    monkeypatch.setattr(subprocess, "run", run)
    get_state_resources(_STACK)
    assert asked == [_STACK]
