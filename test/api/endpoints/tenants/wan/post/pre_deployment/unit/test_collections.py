"""Unit tests for the per-collection views of a computed WAN and role labelling."""

from __future__ import annotations

from typing import Any

import fixtures
from synthesizer import collections as gc
from synthesizer.model import Design, DesignMetrics
from synthesizer.output import design_payload


def _payload() -> dict[str, Any]:
    return design_payload(fixtures.sample_sources(), fixtures.ring_artifacts())


def _design(backbone_ids: tuple[str, ...], transit_ids: tuple[str, ...]) -> Design:
    """A minimal design carrying only the tier ids vertex_role reads."""
    return Design(backbone_ids, transit_ids, [], set(), [], DesignMetrics(0.0, 0.0, 0.0))


def test_vertex_role_backbone_for_selected_pop() -> None:
    """A carrier PoP in the backbone set is labelled backbone."""
    assert gc.vertex_role(fixtures.carrier_pop("a"), _design(("a",), ())) == "backbone"


def test_vertex_role_transit_for_routing_only_pop() -> None:
    """A carrier PoP only used to path is labelled transit."""
    assert gc.vertex_role(fixtures.carrier_pop("a"), _design((), ("a",))) == "transit"


def test_vertex_role_unused_for_unselected_pop() -> None:
    """A carrier PoP neither selected nor crossed by a path is labelled unused."""
    assert gc.vertex_role(fixtures.carrier_pop("a"), _design((), ())) == "unused"


def test_vertex_role_tenant_for_a_site() -> None:
    """A tenant-site demand vertex is labelled tenant."""
    assert gc.vertex_role(fixtures.access_vertex("s"), _design((), ())) == "tenant"


def test_vertex_role_provider_for_a_provider_region() -> None:
    """A provider-region demand vertex is labelled provider."""
    assert gc.vertex_role(fixtures.provider_vertex("r"), _design((), ())) == "provider"


def test_vertices_returns_the_payload_vertices() -> None:
    """vertices() exposes the design payload's vertex list."""
    payload = _payload()
    assert gc.vertices(payload) == payload["vertices"]


def test_edges_combines_access_and_carrier_fiber() -> None:
    """edges() concatenates access homings and carrier-physical edges."""
    payload = _payload()
    assert gc.edges(payload) == payload["access_edges"] + payload["physical_edges"]


def test_backbone_nodes_are_all_tier_backbone() -> None:
    """backbone_nodes() returns only vertices whose tier role is backbone."""
    assert all(vertex["tier_role"] == "backbone" for vertex in gc.backbone_nodes(_payload()))


def test_tenant_nodes_are_all_tier_tenant() -> None:
    """tenant_nodes() returns only tenant-tier demand vertices."""
    assert all(vertex["tier_role"] == "tenant" for vertex in gc.tenant_nodes(_payload()))


def test_provider_nodes_are_all_tier_provider() -> None:
    """provider_nodes() returns only provider-tier demand vertices."""
    assert all(vertex["tier_role"] == "provider" for vertex in gc.provider_nodes(_payload()))


def test_backbone_links_exist_for_a_meshed_design() -> None:
    """A design whose backbone is meshed exposes at least one backbone-to-backbone link."""
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
