"""Unit tests for the FastAPI atomic design endpoints."""

from __future__ import annotations

from pathlib import Path

import fixtures


def test_wan_maps_lists_the_joint_map(tmp_path: Path) -> None:
    """GET /api/wan-maps lists the discovered WAN map by id."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps")
    assert {"id": "joint", "label": "joint"} in response.json()


def test_vertices_returns_a_non_empty_list(tmp_path: Path) -> None:
    """GET .../vertices returns the design's vertices."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps/joint/vertices")
    assert len(response.json()) > 0


def test_edges_includes_access_edges(tmp_path: Path) -> None:
    """GET .../edges groups the design's access, physical, and routed edges."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps/joint/edges")
    assert "access_edges" in response.json()


def test_validation_reports_connected(tmp_path: Path) -> None:
    """GET .../validation returns the solvable design's validation report."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps/joint/validation")
    assert response.json()["connected"] is True


def test_summary_includes_cores(tmp_path: Path) -> None:
    """GET .../summary returns the tier summary."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps/joint/summary")
    assert "cores" in response.json()


def test_unknown_wan_map_returns_404(tmp_path: Path) -> None:
    """An unknown WAN map id yields a 404."""
    response = fixtures.api_client(tmp_path).get("/api/wan-maps/nope/vertices")
    assert response.status_code == 404


def test_index_is_served_at_root(tmp_path: Path) -> None:
    """The static frontend is served at the root path."""
    response = fixtures.api_client(tmp_path).get("/")
    assert "ok" in response.text
