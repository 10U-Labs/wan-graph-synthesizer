"""Per-collection JSON views of a computed customer WAN.

The optimizer's ``design_payload`` (output.py) is one coherent computation; the
entrypoint slices it into the atomic collections the REST API serves (vertices,
edges, and the three tier views) and stores each separately. These are read-only
slices over that already-serialized payload, so they take and return plain dicts.
"""

from __future__ import annotations

from typing import Any


def vertices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The vertices of a computed customer WAN (each carries kind + tier_role)."""
    result: list[dict[str, Any]] = payload["vertices"]
    return result


def edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge of a computed customer WAN: access homings plus carrier fiber."""
    result: list[dict[str, Any]] = payload["access_edges"] + payload["physical_edges"]
    return result


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [vertex for vertex in payload["vertices"] if vertex["tier_role"] == tier_role]


def core_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as core (national) hubs."""
    return _tier(payload, "core")


def aggregation_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as aggregation (regional) hubs."""
    return _tier(payload, "aggregation")


def access_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The demand vertices (installations + CSP regions) homed into the design."""
    return _tier(payload, "access")
