"""End-to-end checks that validate the design the REST API serves.

These exercise the whole stack the browser uses: an in-process server built
over the real ``etc/`` WAN maps, computing the Joint design on demand and
serving it through the atomic endpoints. The assertions confirm the structural
guarantees of the design that comes back over HTTP.
"""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import build_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(name="design", scope="module")
def fixture_design() -> dict[str, Any]:
    """Assemble the Joint design from the live API endpoints."""
    client = TestClient(build_app(REPO_ROOT / "etc", REPO_ROOT / "src" / "www"))
    vertices = client.get("/api/wan-maps/joint/vertices").json()
    edges = client.get("/api/wan-maps/joint/edges").json()
    validation = client.get("/api/wan-maps/joint/validation").json()
    return {"vertices": vertices, "path_uses": edges["path_uses"], "validation": validation}


@pytest.fixture(name="f35_design", scope="module")
def fixture_f35_design() -> dict[str, Any]:
    """Assemble the F-35 design's vertices from the live API endpoints."""
    client = TestClient(build_app(REPO_ROOT / "etc", REPO_ROOT / "src" / "www"))
    return {"vertices": client.get("/api/wan-maps/f_35/vertices").json()}


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


def test_cores_form_full_mesh(design: dict[str, Any]) -> None:
    """Cores form full mesh."""
    assert design["validation"]["cores_full_mesh"] is True


def test_access_vertices_are_dual_homed(design: dict[str, Any]) -> None:
    """Access vertices are dual homed."""
    assert design["validation"]["access_vertices_with_two_aggregation_links"] is True


def test_core_tier_has_at_least_three_vertices(design: dict[str, Any]) -> None:
    """Core tier has at least the minimum three vertices."""
    assert len(core_names(design)) >= 3


def test_every_aggregation_reaches_two_distinct_cores(design: dict[str, Any]) -> None:
    """Every aggregation reaches two distinct cores."""
    targets = core_targets_by_aggregation(design)
    assert all(len(targets[name]) == 2 for name in aggregation_names(design))


def test_goodyear_is_not_an_aggregation(design: dict[str, Any]) -> None:
    """A single-homed leaf such as Goodyear is never selected as an aggregation."""
    assert "Goodyear, AZ" not in aggregation_names(design)


def test_f35_mclean_is_an_aggregation(f35_design: dict[str, Any]) -> None:
    """F-35 pins McLean as an aggregation point."""
    assert "McLean, VA" in aggregation_names(f35_design)


def test_f35_mclean_is_not_a_core(f35_design: dict[str, Any]) -> None:
    """F-35 does not force McLean into the core tier."""
    assert "McLean, VA" not in core_names(f35_design)
