"""Unit tests for the list of resource kinds the drift check can ask the platform about.

The state layer walks what a plan would create and asks about each thing it can. This list
is what decides which of them that is, so a kind missing from it is a resource the layer
walks past in silence -- and silence there reads exactly like a clean state.
"""

from __future__ import annotations

from test_terraform_drift import RESOURCE_CHECKERS, get_supported_resource_types


def test_every_kind_with_a_probe_behind_it_is_offered() -> None:
    """The list is the registry, so a probe added is offered without a second edit."""
    assert get_supported_resource_types() == list(RESOURCE_CHECKERS)


def test_a_kind_with_no_probe_behind_it_is_not_offered() -> None:
    """Offering a kind nothing can ask about would report every one of them absent."""
    assert "aws_kinesis_stream" not in get_supported_resource_types()
