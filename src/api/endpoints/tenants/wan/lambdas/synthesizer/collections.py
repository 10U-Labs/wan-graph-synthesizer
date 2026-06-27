"""Per-collection JSON views of a computed tenant WAN, plus demand-role labelling.

The synthesizer's ``design_payload`` (output.py) is one coherent computation; the
worker slices it into the atomic collections the REST API serves (vertices,
edges, and the tier views) and stores each separately. The slice helpers are
read-only views over that already-serialized payload, so they take and return plain
dicts. :func:`vertex_role` is the authoritative tier-role labeller -- it lives here
because labelling demand as ``tenant`` vs ``csp`` needs the codec's vertex kinds.
"""

from __future__ import annotations

from typing import Any

from synthesizer.codec import CSP_KIND
from synthesizer.input_graph import Vertex
from synthesizer.model import Design, is_carrier_pop


def vertex_role(vertex: Vertex, design: Design) -> str:
    """Return the tier role of a vertex.

    A selected carrier PoP is ``backbone``; a routing-only PoP is ``transit``; an
    unselected PoP is ``unused``. A demand vertex is ``csp`` when its kind is the
    codec's cloud-region kind and ``tenant`` otherwise (a tenant site).
    """
    if not is_carrier_pop(vertex):
        return "csp" if vertex.kind == CSP_KIND else "tenant"
    if vertex.id in design.backbone_ids:
        return "backbone"
    if vertex.id in design.transit_ids:
        return "transit"
    return "unused"


def vertices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The vertices of a computed tenant WAN (each carries kind + tier_role)."""
    result: list[dict[str, Any]] = payload["vertices"]
    return result


def edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge of a computed tenant WAN: access homings plus carrier fiber."""
    result: list[dict[str, Any]] = payload["access_edges"] + payload["physical_edges"]
    return result


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [vertex for vertex in payload["vertices"] if vertex["tier_role"] == tier_role]


def backbone_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as backbone hubs."""
    return _tier(payload, "backbone")


def tenant_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The tenant's own demand vertices (its access sites) homed into the design."""
    return _tier(payload, "tenant")


def csp_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The CSP cloud-region demand vertices homed into the design."""
    return _tier(payload, "csp")
