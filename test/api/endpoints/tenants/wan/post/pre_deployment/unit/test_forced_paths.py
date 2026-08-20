"""Unit tests for operator-forced paths: resolution and routing wiring.

These pin the mechanism -- names resolve to id-typed links against the seated tiers,
and the synthesizer honors them -- rather than any particular city pin. Which tier a
written link acts on is the list it sits in, so each case names the list rather than a
type on the entry.
"""

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

# Two carrier PoPs and one demand site; names equal ids for the ring factories.
SITES = [pop("P0"), pop("P1"), access("A1")]


def test_backbone_link_resolves_to_an_link_key() -> None:
    """A pinned mesh pair between two forced nodes resolves to their link key."""
    links = resolve_forced_links(
        OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.backbone == frozenset({link_key("P0", "P1")})


def test_forced_home_resolves_to_an_ordered_pair() -> None:
    """A forced home resolves to an (access, backbone) id pair, in that order."""
    links = resolve_forced_links(
        OperatorLinks(access=(NamedLink("A1", "P1"),)), SITES, {"P1"}
    )
    assert links.access == frozenset({("A1", "P1")})


def test_excluded_backbone_resolves_to_a_removed_pair() -> None:
    """A pruned mesh pair resolves to a removed link key."""
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.removed_backbone == frozenset({link_key("P0", "P1")})


def test_excluded_backbone_endpoint_need_not_be_forced() -> None:
    """A pruned mesh pair resolves even when neither endpoint is forced."""
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(NamedLink("P0", "P1"),)), SITES, set()
    )
    assert links.removed_backbone == frozenset({link_key("P0", "P1")})


def test_excluded_backbone_unknown_endpoint_is_rejected() -> None:
    """A pruned mesh endpoint absent from the Carrier graph is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(removed_backbone=(NamedLink("Nowhere", "P1"),)), SITES, set()
        )


def test_removed_backbone_pairs_keeps_only_in_set_pairs() -> None:
    """Only pruned pairs with both endpoints in the current backbone set are removed."""
    links = ForcedLinks(removed_backbone=frozenset({link_key("P0", "P1"), link_key("P0", "P9")}))
    assert removed_backbone_pairs({"P0", "P1"}, links) == frozenset({link_key("P0", "P1")})


def test_forced_backbone_pairs_keeps_only_in_set_pairs() -> None:
    """Only forced pairs with both endpoints in the current backbone set are wired."""
    links = ForcedLinks(backbone=frozenset({link_key("P0", "P1"), link_key("P0", "P9")}))
    assert forced_backbone_pairs({"P0", "P1"}, links) == frozenset({link_key("P0", "P1")})


def test_unknown_backbone_endpoint_is_rejected() -> None:
    """A pinned mesh endpoint absent from the Carrier graph is named as a forced path."""
    with pytest.raises(ValueError, match="forced-path"):
        resolve_forced_links(
            OperatorLinks(backbone=(NamedLink("Nowhere", "P1"),)), SITES, {"P1"}
        )


def test_backbone_endpoint_not_forced_is_rejected() -> None:
    """A pinned mesh endpoint that is not a forced backbone node is named as a forced path."""
    with pytest.raises(ValueError, match="forced-path"):
        resolve_forced_links(
            OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0"}
        )


def test_forced_home_target_not_forced_names_the_home_list() -> None:
    """A home's target that the operator did not pin is named as a forced home.

    The operator wrote this entry in `access.forced.homes`, so that is the list the
    message has to send them to -- naming the mesh list sends them to a file they did
    not touch, with no way to learn from the words which one they did.
    """
    with pytest.raises(ValueError, match="forced-home"):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("A1", "P1"),)), SITES, set()
        )


def test_forced_home_target_off_the_carrier_graph_names_the_home_list() -> None:
    """A home's target that is no carrier PoP at all is named as a forced home."""
    with pytest.raises(ValueError, match="forced-home"):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("A1", "Nowhere"),)), SITES, {"P1"}
        )


def test_forced_home_source_that_is_not_demand_is_rejected() -> None:
    """A forced home's source that is not a demand site is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(access=(NamedLink("Nope", "P1"),)), SITES, {"P1"}
        )


def test_a_mesh_pair_is_not_read_as_a_home() -> None:
    """A pair written in the backbone list never lands among the homes.

    The tier comes from the list alone now, so nothing on the entry could redirect it --
    this is the check that the two lists stay apart rather than both feeding one set.
    """
    links = resolve_forced_links(
        OperatorLinks(backbone=(NamedLink("P0", "P1"),)), SITES, {"P0", "P1"}
    )
    assert links.access == frozenset()


def test_no_forced_link_returns_homes_unchanged() -> None:
    """With no forced access link the computed homes are returned untouched."""
    pop_by_id = {"P0": pop("P0", 40.0, -100.0), "P1": pop("P1", 50.0, -100.0)}
    homes = apply_forced_access_homes(
        access("A1", 40.0, -100.0), ["P0", "P1"], ForcedLinks(), pop_by_id, 2
    )
    assert homes == ["P0", "P1"]


def test_forced_access_home_is_pinned_over_a_nearer_facility() -> None:
    """A forced access link pins its backbone node as one of the two homes."""
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
