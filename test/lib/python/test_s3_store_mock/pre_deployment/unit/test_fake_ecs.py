"""Unit tests for the stand-in ECS client that records the tasks a caller starts.

A caller that runs work on ECS is judged on the request it made and on what it did with
the answer, and both are what this double supplies: the requests land in a list the test
reads, and the answer can be made a Spot capacity shortfall instead of a running task.

Getting the shortfall wrong in either direction hides the retry. A double that never
refuses leaves the retry path untested and reports a caller that cannot recover as sound;
one that refuses when it was not asked to fails a caller that is fine.
"""

from __future__ import annotations

from typing import Any

from test_s3_store_mock import fake_ecs


def test_the_request_made_is_the_one_recorded() -> None:
    """The recorded call is the whole of what a test knows about what would have run."""
    started: list[dict[str, Any]] = []
    fake_ecs(started).run_task(cluster="synthesizer", count=1)
    assert started == [{"cluster": "synthesizer", "count": 1}]


def test_a_started_task_comes_back_with_an_arn() -> None:
    """A caller that records the task it started needs an identifier to record."""
    assert fake_ecs([]).run_task(cluster="synthesizer")["tasks"] == [
        {"taskArn": "arn:aws:ecs:task/fake"}
    ]


def test_a_placement_shortfall_yields_no_task() -> None:
    """Spot capacity can be gone, and then nothing started however well the call was formed."""
    assert fake_ecs([], placement_failures=1).run_task(cluster="synthesizer")["tasks"] == []


def test_a_placement_shortfall_says_why_it_placed_nothing() -> None:
    """The reason is what a caller decides between retrying and giving up on."""
    client = fake_ecs([], placement_failures=1)
    assert client.run_task(cluster="synthesizer")["failures"] == [
        {"reason": "Capacity is unavailable at this time."}
    ]


def test_a_retry_after_the_shortfall_places_the_task() -> None:
    """Only the first calls are refused, so a caller that retries gets through."""
    client = fake_ecs([], placement_failures=1)
    client.run_task(cluster="synthesizer")
    assert client.run_task(cluster="synthesizer")["tasks"] == [{"taskArn": "arn:aws:ecs:task/fake"}]


def test_every_attempt_is_recorded_including_the_refused_ones() -> None:
    """How many times a caller tried is the question a retry test asks."""
    started: list[dict[str, Any]] = []
    client = fake_ecs(started, placement_failures=1)
    client.run_task(cluster="synthesizer")
    client.run_task(cluster="synthesizer")
    assert len(started) == 2


def test_a_task_reports_the_tags_it_was_given() -> None:
    """A caller reads its own bookkeeping back off the stopped task's tags."""
    client = fake_ecs([], task_tags={"tenant": "daf"})
    assert client.describe_tasks(tasks=["arn:aws:ecs:task/fake"])["tasks"] == [
        {"tags": [{"key": "tenant", "value": "daf"}]}
    ]


def test_a_task_that_no_longer_exists_is_answered_with_no_task() -> None:
    """ECS forgets a stopped task after an hour, and a caller has to survive the gap."""
    client = fake_ecs([], task_tags=None)
    assert client.describe_tasks(tasks=["arn:aws:ecs:task/fake"])["tasks"] == []
