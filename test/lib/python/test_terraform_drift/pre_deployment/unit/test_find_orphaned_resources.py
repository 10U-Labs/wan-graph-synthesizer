"""Unit tests for finding resources a deployment would create that already exist.

This is the whole of the state layer's answer. A resource the plan means to create that is
already there was made outside OpenTofu or had its state lost, and the deployment will
either fail on it or take it over; either way the layer's job is to say so first, and to
say it in a form somebody can act on without working out the import line themselves.

Both halves it stands on are replaced here -- what the plan would create, and whether each
one exists -- because each has its own tests, and what is under test here is only the
decision made from the two together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import test_terraform_drift
from test_terraform_drift import find_orphaned_resources

_STACK = Path("src/api/endpoints/carriers")
_PLANNED: list[dict[str, object]] = [
    {"type": "aws_s3_bucket", "name": "the-store", "address": "aws_s3_bucket.store", "values": {}}
]


def _planning(monkeypatch: pytest.MonkeyPatch, planned: list[dict[str, object]]) -> None:
    """Have the plan mean to create *planned*."""
    monkeypatch.setattr(test_terraform_drift, "get_planned_creates", lambda _dir: planned)


def _existing(monkeypatch: pytest.MonkeyPatch, exists: bool) -> None:
    """Have the platform answer *exists* about every resource it is asked."""
    monkeypatch.setattr(test_terraform_drift, "check_resource_exists", lambda *_args: exists)


def _found(monkeypatch: pytest.MonkeyPatch, exists: bool = True) -> list[dict[str, str]]:
    """The orphans found when the plan holds one create and the platform answers *exists*."""
    _planning(monkeypatch, _PLANNED)
    _existing(monkeypatch, exists)
    return find_orphaned_resources(_STACK)


def test_a_planned_resource_that_already_exists_is_an_orphan(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """This is the collision the layer exists to find, and it names the resource."""
    assert [orphan["name"] for orphan in _found(monkeypatch)] == ["the-store"]


def test_the_orphan_carries_the_kind_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two resources can share a name across services, so the kind travels with it."""
    assert [orphan["type"] for orphan in _found(monkeypatch)] == ["aws_s3_bucket"]


def test_the_orphan_carries_the_address_the_stack_would_have_given_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The address is where the resource belongs in state once it is taken over."""
    assert [orphan["address"] for orphan in _found(monkeypatch)] == ["aws_s3_bucket.store"]


def test_the_orphan_comes_with_the_command_that_settles_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A finding nobody can act on stops a deployment without shortening it."""
    assert [orphan["import_command"] for orphan in _found(monkeypatch)] == [
        "tofu import aws_s3_bucket.store the-store"
    ]


def test_a_planned_resource_that_does_not_exist_is_not_an_orphan(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating something that is not there is what a deployment is for."""
    assert len(_found(monkeypatch, exists=False)) == 0


def test_a_plan_that_would_create_nothing_finds_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A stack already reconciled plans no creates, and there is nothing to collide with."""
    _planning(monkeypatch, [])
    _existing(monkeypatch, True)
    assert len(find_orphaned_resources(_STACK)) == 0


def test_each_resource_is_asked_about_in_the_region_given(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller checking another region must not be answered about this one."""
    asked: list[Any] = []

    def exists(_type: str, _name: str, region: str) -> bool:
        """Record the region the platform was asked in and answer that nothing is there."""
        asked.append(region)
        return False

    _planning(monkeypatch, _PLANNED)
    monkeypatch.setattr(test_terraform_drift, "check_resource_exists", exists)
    find_orphaned_resources(_STACK, region="eu-west-1")
    assert asked == ["eu-west-1"]
