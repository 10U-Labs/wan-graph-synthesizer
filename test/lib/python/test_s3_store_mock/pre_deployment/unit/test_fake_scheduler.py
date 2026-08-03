"""Unit tests for the stand-in EventBridge Scheduler client.

A caller that schedules future work is judged on the schedule it asked for, since nothing
else about it can be observed before the time comes. The double keeps each request so the
test can read the expression, the target and the name back out of it.
"""

from __future__ import annotations

from typing import Any

from test_s3_store_mock import fake_scheduler


def test_the_schedule_asked_for_is_the_one_recorded() -> None:
    """The recorded request is the whole of what a caller promised to run later."""
    schedules: list[dict[str, Any]] = []
    fake_scheduler(schedules).create_schedule(Name="rebuild-daf", ScheduleExpression="rate(1 day)")
    assert schedules == [{"Name": "rebuild-daf", "ScheduleExpression": "rate(1 day)"}]


def test_a_created_schedule_comes_back_with_an_arn() -> None:
    """A caller that records what it scheduled needs an identifier to record."""
    created = fake_scheduler([]).create_schedule(Name="rebuild-daf")
    assert created["ScheduleArn"] == "arn:aws:scheduler:schedule/fake"


def test_each_schedule_is_recorded_in_the_order_it_was_asked_for() -> None:
    """Two schedules are two requests, and which came first is part of what is under test."""
    schedules: list[dict[str, Any]] = []
    client = fake_scheduler(schedules)
    client.create_schedule(Name="rebuild-daf")
    client.create_schedule(Name="rebuild-dow")
    assert [schedule["Name"] for schedule in schedules] == ["rebuild-daf", "rebuild-dow"]
