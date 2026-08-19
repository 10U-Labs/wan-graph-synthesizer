"""Unit tests for the decision that a tenant's network is finished being decided.

These are the states the service records for a build. The dispatcher writes ``creating``
in the request path of the POST that starts one, the synthesizer writes ``synthesizing``
when it picks the work up and ``success`` when it has published, and a reader that
measures a network while either of the first two is showing measures one the operator has
already replaced. A build can also end without a network, as ``fail`` when the synthesizer
decides none is possible or as ``timeout`` when AWS kills it part-way, and both of those
are finished: waiting cannot improve either one. Nothing else is consulted: what the build
was built from is the seed run's business, and reading it back here is what left six of
eight settings invisible (GitHub issue #47).
"""

from __future__ import annotations

from test_published_designs import settled


def test_a_build_the_service_has_only_accepted_is_not_settled() -> None:
    """``creating`` is the POST answering; the synthesizer has not started yet."""
    assert settled({"status": "creating"}) is False


def test_a_build_still_running_is_not_settled() -> None:
    """``synthesizing`` is the synthesizer at work, with nothing published yet."""
    assert settled({"status": "synthesizing"}) is False


def test_a_build_that_has_published_is_settled() -> None:
    """``success`` is a network the tier can measure, and no later build is owed."""
    assert settled({"status": "success", "tenant": "daf"}) is True


def test_a_build_aws_killed_is_settled() -> None:
    """``timeout`` is a build cut off part-way, and no later word is coming for it."""
    assert settled({"status": "timeout", "tenant": "daf"}) is True
