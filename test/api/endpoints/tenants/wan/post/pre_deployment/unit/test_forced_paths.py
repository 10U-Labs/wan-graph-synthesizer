from __future__ import annotations

import pytest

import fixtures
from synthesizer.forced import (
    apply_forced_access_homes,
    forced_backbone_pairs,
    removed_backbone_pairs,
)
from synthesizer.overrides import resolve_forced_links
from synthesizer.model import ForcedLinks, NamedLink, OperatorLinks
from synthesizer.input_graph import link_key

pop = fixtures.carrier_pop
access = fixtures.access_site

SITES = [pop("P0"), pop("P1"), access("A1")]


def test_backbone_link_resolves_to_an_link_key() -> None:
    links = resolve_forced_links(
        OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.backbone == frozenset({link_key("P0", "P1")})


def test_forced_home_resolves_to_an_ordered_pair() -> None:
    links = resolve_forced_links(
        OperatorLinks(access=(NamedLink("A1", "P1"),)), SITES, {"P1"}
    )
    assert links.access == frozenset({("A1", "P1")})


def test_excluded_backbone_resolves_to_a_removed_pair() -> None:
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.removed_backbone == frozenset({link_key("P0", "P1")})


def test_excluded_backbone_endpoint_need_not_be_forced() -> None:
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(NamedLink("P0", "P1"),)), SITES, set()
    )
    assert links.removed_backbone == frozenset({link_key("P0", "P1")})


def test_excluded_backbone_unknown_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(removed_backbone=(NamedLink("Nowhere", "P1"),)), SITES, set()
        )


def test_removed_backbone_pairs_keeps_only_in_set_pairs() -> None:
    links = ForcedLinks(removed_backbone=frozenset({link_key("P0", "P1"), link_key("P0", "P9")}))
    assert removed_backbone_pairs({"P0", "P1"}, links) == frozenset({link_key("P0", "P1")})


def test_forced_backbone_pairs_keeps_only_in_set_pairs() -> None:
    links = ForcedLinks(backbone=frozenset({link_key("P0", "P1"), link_key("P0", "P9")}))
    assert forced_backbone_pairs({"P0", "P1"}, links) == frozenset({link_key("P0", "P1")})


def test_unknown_backbone_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="forced-path"):
        resolve_forced_links(
            OperatorLinks(backbone=(NamedLink("Nowhere", "P1"),)), SITES, {"P1"}
        )


def test_backbone_endpoint_not_forced_is_rejected() -> None:
    with pytest.raises(ValueError, match="forced-path"):
        resolve_forced_links(
            OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0"}
        )


def test_forced_home_target_not_forced_names_the_home_list() -> None:
    with pytest.raises(ValueError, match="forced-home"):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("A1", "P1"),)), SITES, set()
        )


def test_forced_home_target_off_the_carrier_graph_names_the_home_list() -> None:
    with pytest.raises(ValueError, match="forced-home"):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("A1", "Nowhere"),)), SITES, {"P1"}
        )


def test_forced_home_source_that_is_not_demand_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("Nope", "P1"),)), SITES, {"P1"}
        )


def test_a_mesh_pair_is_not_read_as_a_home() -> None:
    links = resolve_forced_links(
        OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.access == frozenset()


def test_no_forced_link_returns_homes_unchanged() -> None:
    pop_by_id = {"P0": pop("P0", 40.0, -100.0), "P1": pop("P1", 50.0, -100.0)}
    homes = apply_forced_access_homes(
        access("A1", 40.0, -100.0), ["P0", "P1"], ForcedLinks(), pop_by_id, 2
    )
    assert homes == ["P0", "P1"]


def test_forced_access_home_is_pinned_over_a_nearer_facility() -> None:
    links = ForcedLinks(access=frozenset({("A1", "P3")}))
    pop_by_id = {
        "P0": pop("P0", 40.0, -100.1),
        "P1": pop("P1", 50.0, -100.0),
        "P3": pop("P3", 41.0, -99.0),
    }
    homes = apply_forced_access_homes(
        access("A1", 40.0, -100.0), ["P0", "P1"], links, pop_by_id, 2
    )
    assert set(homes) == {"P3", "P0"}
