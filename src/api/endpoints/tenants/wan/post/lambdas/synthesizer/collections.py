from __future__ import annotations

from typing import Any

from synthesizer.codec import PROVIDER_KIND
from synthesizer.input_graph import Site
from synthesizer.model import Synthesis, is_carrier_pop


def site_role(site: Site, synthesis: Synthesis) -> str:
    if not is_carrier_pop(site):
        return "provider" if site.kind == PROVIDER_KIND else "tenant"
    if site.id in synthesis.backbone_ids:
        return "backbone"
    if site.id in synthesis.transit_ids:
        return "transit"
    return "unused"


def sites(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = payload["sites"]
    return result


def paths(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = payload["access_paths"] + payload["fiber_segments"]
    return result


def backbone_links(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [use for use in payload["path_uses"] if use["purpose"] == "backbone_mesh"]


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [site for site in payload["sites"] if site["tier_role"] == tier_role]


def backbone_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _tier(payload, "backbone")


def tenant_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _tier(payload, "tenant")


def provider_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _tier(payload, "provider")
