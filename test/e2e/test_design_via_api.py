"""End-to-end checks over a synthetic fixture WAN map served by the REST API.

These exercise the whole stack the browser uses -- an in-process server built
over a fixture config, computing a design on demand and serving it through the
atomic endpoints -- and assert the structural guarantees of the design that
comes back over HTTP. The fixture config is built by the test, so the design
logic is exercised without any dependency on the production ``etc/`` files.
"""

from __future__ import annotations

import collections
from typing import Any

import pytest
from fastapi.testclient import TestClient

import fixtures


@pytest.fixture(name="client", scope="module")
def fixture_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Build an in-process client over a synthetic fixture WAN map."""
    return fixtures.api_client(tmp_path_factory.mktemp("e2e"))


@pytest.fixture(name="design", scope="module")
def fixture_design(client: TestClient) -> dict[str, Any]:
    """Assemble the design from the live API endpoints."""
    vertices = client.get("/api/wan-maps/joint/vertices").json()
    edges = client.get("/api/wan-maps/joint/edges").json()
    validation = client.get("/api/wan-maps/joint/validation").json()
    return {"vertices": vertices, "path_uses": edges["path_uses"], "validation": validation}


def core_names(design: dict[str, Any]) -> set[str]:
    """Test helper: build core names."""
    return {vertex["name"] for vertex in design["vertices"] if vertex["tier_role"] == "core"}


def aggregation_names(design: dict[str, Any]) -> set[str]:
    """Test helper: build aggregation names."""
    return {vertex["name"] for vertex in design["vertices"] if vertex["tier_role"] == "aggregation"}


def core_targets_by_aggregation(design: dict[str, Any]) -> dict[str, set[str]]:
    """Test helper: build core targets by aggregation."""
    targets: dict[str, set[str]] = collections.defaultdict(set)
    for use in design["path_uses"]:
        if use["purpose"] == "aggregation_to_core":
            targets[use["source_name"]].add(use["target_name"])
    return targets


def test_design_is_connected(design: dict[str, Any]) -> None:
    """Design is connected."""
    assert design["validation"]["connected"] is True


def test_aggregations_are_dual_homed_to_cores(design: dict[str, Any]) -> None:
    """Aggregations are dual homed to cores."""
    assert design["validation"]["aggregations_dual_homed_to_cores"] is True


def test_cores_meet_the_backbone_link_target(design: dict[str, Any]) -> None:
    """Every core wires to its configured number of nearest cores on the backbone."""
    assert design["validation"]["cores_meet_backbone_link_target"] is True


def test_access_vertices_are_dual_homed(design: dict[str, Any]) -> None:
    """Access vertices are dual homed."""
    assert design["validation"]["access_vertices_with_required_aggregation_links"] is True


def test_core_tier_meets_the_minimum(design: dict[str, Any]) -> None:
    """The core tier has at least the configured minimum of two vertices."""
    assert len(core_names(design)) >= 2


def test_every_aggregation_reaches_two_distinct_cores(design: dict[str, Any]) -> None:
    """Every aggregation reaches two distinct cores."""
    targets = core_targets_by_aggregation(design)
    assert all(len(targets[name]) == 2 for name in aggregation_names(design))
