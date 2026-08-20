"""Unit tests for the per-collection views of a computed WAN and role labelling."""

from __future__ import annotations

from typing import Any

import fixtures
from synthesizer import collections as gc
from synthesizer.model import Synthesis, SynthesisMetrics
from synthesizer.output import synthesis_payload


def _payload() -> dict[str, Any]:
    return synthesis_payload(fixtures.sample_sources(), fixtures.ring_artifacts())


def _synthesis(backbone_ids: tuple[str, ...], transit_ids: tuple[str, ...]) -> Synthesis:
    """A minimal synthesis carrying only the tier ids site_role reads."""
    return Synthesis(backbone_ids, transit_ids, [], set(), [], SynthesisMetrics(0.0, 0.0, 0.0))


def test_site_role_backbone_for_selected_pop() -> None:
    """A carrier PoP in the backbone set is labelled backbone."""
    assert gc.site_role(fixtures.carrier_pop("a"), _synthesis(("a",), ())) == "backbone"


def test_site_role_transit_for_routing_only_pop() -> None:
    """A carrier PoP only used to path is labelled transit."""
    assert gc.site_role(fixtures.carrier_pop("a"), _synthesis((), ("a",))) == "transit"


def test_site_role_unused_for_unselected_pop() -> None:
    """A carrier PoP neither selected nor crossed by a path is labelled unused."""
    assert gc.site_role(fixtures.carrier_pop("a"), _synthesis((), ())) == "unused"


def test_site_role_tenant_for_a_site() -> None:
    """A tenant-site demand site is labelled tenant."""
    assert gc.site_role(fixtures.access_site("s"), _synthesis((), ())) == "tenant"


def test_site_role_provider_for_a_provider_region() -> None:
    """A provider-region demand site is labelled provider."""
    assert gc.site_role(fixtures.provider_site("r"), _synthesis((), ())) == "provider"


def test_sites_returns_the_payload_sites() -> None:
    """sites() exposes the synthesis payload's site list."""
    payload = _payload()
    assert gc.sites(payload) == payload["sites"]


def test_links_combines_access_and_carrier_fiber() -> None:
    """links() concatenates access homings and carrier-physical links."""
    payload = _payload()
    assert gc.links(payload) == payload["access_paths"] + payload["fiber_segments"]


def test_backbone_nodes_are_all_tier_backbone() -> None:
    """backbone_nodes() returns only sites whose tier role is backbone."""
    assert all(site["tier_role"] == "backbone" for site in gc.backbone_nodes(_payload()))


def test_tenant_nodes_are_all_tier_tenant() -> None:
    """tenant_nodes() returns only tenant-tier demand sites."""
    assert all(site["tier_role"] == "tenant" for site in gc.tenant_nodes(_payload()))


def test_provider_nodes_are_all_tier_provider() -> None:
    """provider_nodes() returns only provider-tier demand sites."""
    assert all(site["tier_role"] == "provider" for site in gc.provider_nodes(_payload()))


def test_backbone_links_exist_for_a_meshed_synthesis() -> None:
    """A synthesis whose backbone is meshed exposes at least one backbone-to-backbone link."""
    assert gc.backbone_links(_payload())


def test_backbone_links_are_all_backbone_mesh_uses() -> None:
    """backbone_links() returns only the path uses recorded for the backbone mesh."""
    assert all(link["purpose"] == "backbone_mesh" for link in gc.backbone_links(_payload()))


def test_backbone_links_omit_other_path_uses() -> None:
    """A path use recorded for any other purpose is left out."""
    assert gc.backbone_links({"path_uses": [{"purpose": "access"}]}) == []


def test_backbone_links_name_both_endpoints() -> None:
    """Every link carries the names of the two backbone nodes it joins."""
    assert all(
        link["source_name"] and link["target_name"] for link in gc.backbone_links(_payload())
    )
