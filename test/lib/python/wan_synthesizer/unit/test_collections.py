"""Unit tests for the per-collection JSON views of a computed WAN."""

from __future__ import annotations

from typing import Any

import fixtures
from wan_synthesizer import collections as gc
from wan_synthesizer.output import design_payload


def _payload() -> dict[str, Any]:
    return design_payload(fixtures.sample_sources(), fixtures.ring_artifacts())


def test_vertices_returns_the_payload_vertices() -> None:
    """vertices() exposes the design payload's vertex list."""
    payload = _payload()
    assert gc.vertices(payload) == payload["vertices"]


def test_edges_combines_access_and_carrier_fiber() -> None:
    """edges() concatenates access homings and carrier-physical edges."""
    payload = _payload()
    assert gc.edges(payload) == payload["access_edges"] + payload["physical_edges"]


def test_core_nodes_are_all_tier_core() -> None:
    """core_nodes() returns only vertices whose tier role is core."""
    assert all(vertex["tier_role"] == "core" for vertex in gc.core_nodes(_payload()))


def test_aggregation_points_are_all_tier_aggregation() -> None:
    """aggregation_points() returns only aggregation-tier vertices."""
    points = gc.aggregation_points(_payload())
    assert all(vertex["tier_role"] == "aggregation" for vertex in points)


def test_access_nodes_are_all_tier_access() -> None:
    """access_nodes() returns only access-tier vertices."""
    assert all(vertex["tier_role"] == "access" for vertex in gc.access_nodes(_payload()))
