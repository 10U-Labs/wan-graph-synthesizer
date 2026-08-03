"""Unit tests for reading what a plan would create out of ``tofu plan -json``.

The state layer is derived from the deployment tool's own dry run rather than from a
hand-written list, and this is the reading that derives it. Everything it drops, the layer
never asks about: a create it fails to recognise is a resource that can be sitting in the
way untracked with nothing to report it, which is the one thing that layer exists for.

The plan itself is replaced here. What is under test is the reading of its output, and
every shape that output can take -- including the malformed lines a real ``tofu`` mixes in
with the JSON ones.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_terraform_drift import _NAME_FIELDS, get_planned_creates

_STACK = Path("src/api/endpoints/carriers")


def _line(resource_type: str, after: dict[str, Any], address: str = "aws.thing") -> str:
    """One ``planned_change`` line announcing a create of *resource_type*."""
    return json.dumps({
        "type": "planned_change",
        "change": {
            "action": "create",
            "resource": {"resource_type": resource_type, "addr": address},
            "change": {"after": after},
        },
    })


def _planning(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    """Have the plan print *lines* and say nothing else."""
    printed = subprocess.CompletedProcess(
        args=["tofu"], returncode=0, stdout="\n".join(lines), stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: printed)


@pytest.mark.parametrize(("resource_type", "field"), sorted(_NAME_FIELDS.items()))
def test_each_kind_is_named_by_the_attribute_that_carries_its_identifier(
        resource_type: str, field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bucket is named by its bucket and a function by its function name, so both are read."""
    _planning(monkeypatch, _line(resource_type, {field: "the-planned-name"}))
    assert [create["name"] for create in get_planned_creates(_STACK)] == ["the-planned-name"]


def test_the_kind_planned_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The kind decides which probe the layer asks, so it travels with the name."""
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store"}))
    assert [create["type"] for create in get_planned_creates(_STACK)] == ["aws_s3_bucket"]


def test_the_address_planned_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The address is what an import command has to name, so a finding can be acted on."""
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store"}, "aws_s3_bucket.store"))
    assert [create["address"] for create in get_planned_creates(_STACK)] == ["aws_s3_bucket.store"]


def test_the_planned_values_are_carried_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything the plan says about the resource stays available to the caller."""
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": "the-store", "acl": "private"}))
    assert [create["values"] for create in get_planned_creates(_STACK)] == [
        {"bucket": "the-store", "acl": "private"}
    ]


def test_a_line_that_is_not_json_is_stepped_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real plan writes human lines among the machine ones, and they are not findings."""
    _planning(monkeypatch, "Initializing the backend...", _line("aws_s3_bucket", {"bucket": "b"}))
    assert len(get_planned_creates(_STACK)) == 1


def test_an_entry_that_is_not_a_planned_change_is_stepped_over(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan reports its own progress in the same stream, and none of it is a create."""
    _planning(monkeypatch, json.dumps({"type": "version", "terraform": "1.6.0"}))
    assert len(get_planned_creates(_STACK)) == 0


def test_a_change_that_is_not_a_create_is_stepped_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """An update or a delete is a resource already tracked, and not what is being looked for."""
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
    """Reporting a create nothing can be asked about would fail the layer on every run."""
    _planning(monkeypatch, _line("aws_kinesis_stream", {"name": "the-stream"}))
    assert len(get_planned_creates(_STACK)) == 0


def test_a_create_whose_identifier_is_not_known_yet_is_stepped_over(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A name the plan computes at apply time cannot be asked about before it exists."""
    _planning(monkeypatch, _line("aws_s3_bucket", {"bucket": ""}))
    assert len(get_planned_creates(_STACK)) == 0


def test_the_plan_is_run_in_the_stack_directory_it_was_given(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A plan run anywhere else describes another stack, or no stack at all."""
    ran: list[Any] = []
    printed = subprocess.CompletedProcess(args=["tofu"], returncode=0, stdout="", stderr="")

    def run(_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Record where the plan was asked to run and print nothing."""
        ran.append(kwargs["cwd"])
        return printed

    monkeypatch.setattr(subprocess, "run", run)
    get_planned_creates(_STACK)
    assert ran == [_STACK]
