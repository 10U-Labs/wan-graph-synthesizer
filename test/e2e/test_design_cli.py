"""End-to-end tests that run the design CLI on the real project inputs."""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

import pytest

import fixtures
from wan_designer import main

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(name="design", scope="module")
def fixture_design(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Fixture providing the design."""
    output_dir = tmp_path_factory.mktemp("design")
    exit_code = main(
        fixtures.design_args(
            REPO_ROOT / "f35_sentinel_secret_regions_carrier_400g.kmz",
            REPO_ROOT / "data" / "carrier_edges.csv",
            output_dir,
            roles=str(REPO_ROOT / "data" / "carrier_pop_roles.csv"),
        )
    )
    text = (output_dir / "network_design.json").read_text(encoding="utf-8")
    payload: dict[str, Any] = json.loads(text)
    payload["_exit_code"] = exit_code
    return payload


def core_names(design: dict[str, Any]) -> set[str]:
    """Test helper: build core names."""
    return {node["name"] for node in design["nodes"] if node["tier_role"] == "core"}


def aggregation_names(design: dict[str, Any]) -> set[str]:
    """Test helper: build aggregation names."""
    return {node["name"] for node in design["nodes"] if node["tier_role"] == "aggregation"}


def core_targets_by_aggregation(design: dict[str, Any]) -> dict[str, set[str]]:
    """Test helper: build core targets by aggregation."""
    targets: dict[str, set[str]] = collections.defaultdict(set)
    for use in design["path_uses"]:
        if use["purpose"] == "aggregation_to_core":
            targets[use["source_name"]].add(use["target_name"])
    return targets


def test_cli_exits_successfully(design: dict[str, Any]) -> None:
    """Cli exits successfully."""
    assert design["_exit_code"] == 0


def test_design_is_connected(design: dict[str, Any]) -> None:
    """Design is connected."""
    assert design["validation"]["connected"] is True


def test_aggregations_are_dual_homed_to_cores(design: dict[str, Any]) -> None:
    """Aggregations are dual homed to cores."""
    assert design["validation"]["aggregations_dual_homed_to_cores"] is True


def test_cores_form_full_mesh(design: dict[str, Any]) -> None:
    """Cores form full mesh."""
    assert design["validation"]["cores_full_mesh"] is True


def test_access_nodes_are_dual_homed(design: dict[str, Any]) -> None:
    """Access nodes are dual homed."""
    assert design["validation"]["access_nodes_with_two_aggregation_links"] is True


def test_core_tier_has_three_nodes(design: dict[str, Any]) -> None:
    """Core tier has three nodes."""
    assert len(core_names(design)) == 3


def test_every_aggregation_reaches_two_distinct_cores(design: dict[str, Any]) -> None:
    """Every aggregation reaches two distinct cores."""
    targets = core_targets_by_aggregation(design)
    assert all(len(targets[name]) == 2 for name in aggregation_names(design))


def test_degree_one_pops_are_not_aggregations(design: dict[str, Any]) -> None:
    """Degree one pops are not aggregations."""
    assert aggregation_names(design).isdisjoint({"Boston, MA", "Goodyear, AZ"})
