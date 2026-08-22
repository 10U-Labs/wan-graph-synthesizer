from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_terraform_drift import _NAME_FIELDS, get_planned_creates

_STACK = Path("src/api/endpoints/carriers")


def _line(resource_type: str, after: dict[str, Any], address: str = "aws.thing") -> str:
    return json.dumps({
        "type": "planned_change",
        "change": {
            "action": "create",
            "resource": {"resource_type": resource_type, "addr": address},
            "change": {"after": after},
        },
    })


def _planning(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    printed = subprocess.CompletedProcess(
        args=["tofu"], returncode=0, stdout="\n".join(lines), stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: printed)


@pytest.mark.parametrize(("resource_type", "field"), sorted(_NAME_FIELDS.items()))
def test_each_kind_is_named_by_the_attribute_that_carries_its_identifier(
        resource_type: str, field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line(resource_type, {field: "the-planned-name"}))
    assert [create["name"] for create in get_planned_creates(_STACK)] == ["the-planned-name"]


def test_the_kind_planned_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store"}))
    assert [create["type"] for create in get_planned_creates(_STACK)] == ["aws_s3_bucket"]


def test_the_address_planned_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store"}, "aws_s3_bucket.store"))
    assert [create["address"] for create in get_planned_creates(_STACK)] == ["aws_s3_bucket.store"]


def test_the_planned_values_are_carried_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store", "acl": "private"}))
    assert [create["values"] for create in get_planned_creates(_STACK)] == [
        {"bucket": "the-store", "acl": "private"}
    ]


def test_a_line_that_is_not_json_is_stepped_over(monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, "Initializing the backend...", _line("aws_s3_bucket", {"bucket": "b"}))
    assert len(get_planned_creates(_STACK)) == 1


def test_an_entry_that_is_not_a_planned_change_is_stepped_over(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, json.dumps({"type": "version", "terraform": "1.6.0"}))
    assert len(get_planned_creates(_STACK)) == 0


def test_a_change_that_is_not_a_create_is_stepped_over(monkeypatch: pytest.MonkeyPatch) -> None:
    updated = json.dumps({
        "type": "planned_change",
        "change": {
            "action": "update",
            "resource": {"resource_type": "aws_s3_bucket", "addr": "aws_s3_bucket.store"},
            "change": {"after": {"bucket": "the-store"}},
        },
    })
    _planning(monkeypatch, updated)
    assert len(get_planned_creates(_STACK)) == 0


def test_a_kind_with_no_probe_behind_it_is_stepped_over(monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line("aws_kinesis_stream", {"name": "the-stream"}))
    assert len(get_planned_creates(_STACK)) == 0


def test_a_create_whose_identifier_is_not_known_yet_is_stepped_over(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": ""}))
    assert len(get_planned_creates(_STACK)) == 0


def test_the_plan_is_run_in_the_stack_directory_it_was_given(
        monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []
    printed = subprocess.CompletedProcess(args=["tofu"], returncode=0, stdout="", stderr="")

    def run(_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ran.append(kwargs["cwd"])
        return printed

    monkeypatch.setattr(subprocess, "run", run)
    get_planned_creates(_STACK)
    assert ran == [_STACK]
