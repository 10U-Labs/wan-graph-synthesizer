"""Per-collection JSON views of a computed tenant WAN, plus demand-role labelling.

The synthesizer's ``synthesis_payload`` (output.py) is one coherent computation; the
handler slices it into the atomic collections the REST API serves (sites,
links, and the tier views) and stores each separately. The slice helpers are
read-only views over that already-serialized payload, so they take and return plain
dicts. :func:`site_role` is the authoritative tier-role labeller -- it lives here
because labelling demand as ``tenant`` vs ``provider`` needs the codec's site kinds.
"""

from __future__ import annotations

from typing import Any

from synthesizer.codec import PROVIDER_KIND
from synthesizer.input_graph import Site
from synthesizer.model import Synthesis, is_carrier_pop


def site_role(site: Site, synthesis: Synthesis) -> str:
    """Return the tier role of a site.

    A selected carrier PoP is ``backbone``; a routing-only PoP is ``transit``; an
    unselected PoP is ``unused``. A demand site is ``provider`` when its kind is the
    codec's provider-region kind and ``tenant`` otherwise (a tenant site).
    """
    if not is_carrier_pop(site):
        return "provider" if site.kind == PROVIDER_KIND else "tenant"
    if site.id in synthesis.backbone_ids:
        return "backbone"
    if site.id in synthesis.transit_ids:
        return "transit"
    return "unused"


def sites(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The sites of a computed tenant WAN (each carries kind + tier_role)."""
    result: list[dict[str, Any]] = payload["sites"]
    return result


def paths(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every link of a computed tenant WAN: access homings plus carrier fiber."""
    result: list[dict[str, Any]] = payload["access_paths"] + payload["fiber_segments"]
    return result


def backbone_links(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The logical backbone-to-backbone links of a computed tenant WAN.

    One entry per ``backbone_mesh`` path use: the two hubs the link joins, the
    distance, and the physical path it takes. These are the mesh links themselves --
    including any the operator forced -- which no other collection exposes, because
    ``links`` carries only access homings and carrier fiber.
    """
    return [use for use in payload["path_uses"] if use["purpose"] == "backbone_mesh"]


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [site for site in payload["sites"] if site["tier_role"] == tier_role]


def backbone_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the synthesis selected as backbone hubs."""
    return _tier(payload, "backbone")


def tenant_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The tenant's own demand sites (its access sites) homed into the synthesis."""
    return _tier(payload, "tenant")


def provider_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The provider-region demand sites homed into the synthesis."""
    return _tier(payload, "provider")
