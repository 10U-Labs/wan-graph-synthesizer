from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_terraform_drift import get_state_resources

_STACK = Path("src/api/endpoints/carriers")


def _listing(monkeypatch: pytest.MonkeyPatch, printed: str, returncode: int = 0) -> None:
    answer = subprocess.CompletedProcess(
        args=["tofu"], returncode=returncode, stdout=printed, stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: answer)


def test_each_address_printed_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _listing(monkeypatch, "aws_s3_bucket.store\naws_lambda_function.carriers\n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store", "aws_lambda_function.carriers"]


def test_the_spacing_around_an_address_is_not_part_of_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _listing(monkeypatch, "  aws_s3_bucket.store  \n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store"]


def test_a_blank_line_is_not_an_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _listing(monkeypatch, "aws_s3_bucket.store\n\n")
    assert get_state_resources(_STACK) == ["aws_s3_bucket.store"]


def test_a_stack_tracking_nothing_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _listing(monkeypatch, "")
    assert get_state_resources(_STACK) == []


def test_a_command_that_failed_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _listing(monkeypatch, "aws_s3_bucket.store\n", returncode=1)
    assert get_state_resources(_STACK) == []


def test_the_state_is_listed_in_the_stack_directory_it_was_given(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []
    answer = subprocess.CompletedProcess(args=["tofu"], returncode=0, stdout="", stderr="")

    def run(_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        asked.append(kwargs["cwd"])
        return answer

    monkeypatch.setattr(subprocess, "run", run)
    get_state_resources(_STACK)
    assert asked == [_STACK]
