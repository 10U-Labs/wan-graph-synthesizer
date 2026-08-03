"""Unit tests for the decision that a tenant's network is finished being decided.

These are the three states the service records for a build. The dispatcher writes
``creating`` in the request path of the POST that starts one, the synthesizer writes
``building`` when it picks the work up and ``ready`` when it has published, and a reader
that measures a network while either of the first two is showing measures one the operator
has already replaced. Nothing else is consulted: what the build was built from is the seed
run's business, and reading it back here is what left six of eight settings invisible
(GitHub issue #47).
"""

from __future__ import annotations

from test_published_designs import settled


def test_a_build_the_service_has_only_accepted_is_not_settled() -> None:
    """``creating`` is the POST answering; the synthesizer has not started yet."""
    assert settled({"status": "creating"}) is False


def test_a_build_still_running_is_not_settled() -> None:
    """``building`` is the synthesizer at work, with nothing published yet."""
    assert settled({"status": "building"}) is False


def test_a_build_that_has_published_is_settled() -> None:
    """``ready`` is a network the tier can measure, and no later build is owed."""
    assert settled({"status": "ready", "tenant": "daf"}) is True
