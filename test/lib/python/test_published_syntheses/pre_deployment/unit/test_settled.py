from __future__ import annotations

from test_published_syntheses import settled


def test_a_build_the_service_has_only_accepted_is_not_settled() -> None:
    assert settled({"status": "creating"}) is False


def test_a_build_still_running_is_not_settled() -> None:
    assert settled({"status": "synthesizing"}) is False


def test_a_build_that_has_published_is_settled() -> None:
    assert settled({"status": "success", "tenant": "daf"}) is True


def test_a_build_aws_killed_is_settled() -> None:
    assert settled({"status": "timeout", "tenant": "daf"}) is True
