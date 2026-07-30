"""Unit tests for operator-forced connections: resolution and routing wiring.

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
from synthesizer.model import ForcedConnection, ForcedLinks, OperatorLinks
from synthesizer.input_graph import edge_key

pop = fixtures.carrier_pop
access = fixtures.access_vertex

# Two carrier PoPs and one demand vertex; names equal ids for the ring factories.
VERTICES = [pop("P0"), pop("P1"), access("A1")]


def test_backbone_link_resolves_to_an_edge_key() -> None:
    """A pinned mesh pair between two forced nodes resolves to their edge key."""
    links = resolve_forced_links(
        OperatorLinks(backbone=(ForcedConnection("P0", "P1"),)), VERTICES, {"P0", "P1"}
    )
    assert links.backbone == frozenset({edge_key("P0", "P1")})


def test_forced_home_resolves_to_an_ordered_pair() -> None:
    """A forced home resolves to an (access, backbone) id pair, in that order."""
    links = resolve_forced_links(
        OperatorLinks(access=(ForcedConnection("A1", "P1"),)), VERTICES, {"P1"}
    )
    assert links.access == frozenset({("A1", "P1")})


def test_excluded_backbone_resolves_to_a_removed_pair() -> None:
    """A pruned mesh pair resolves to a removed edge key."""
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(ForcedConnection("P0", "P1"),)), VERTICES, {"P0", "P1"}
    )
    assert links.removed_backbone == frozenset({edge_key("P0", "P1")})


def test_excluded_backbone_endpoint_need_not_be_forced() -> None:
    """A pruned mesh pair resolves even when neither endpoint is forced."""
    links = resolve_forced_links(
        OperatorLinks(removed_backbone=(ForcedConnection("P0", "P1"),)), VERTICES, set()
    )
    assert links.removed_backbone == frozenset({edge_key("P0", "P1")})


def test_excluded_backbone_unknown_endpoint_is_rejected() -> None:
    """A pruned mesh endpoint absent from the Carrier graph is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(removed_backbone=(ForcedConnection("Nowhere", "P1"),)), VERTICES, set()
        )


def test_removed_backbone_pairs_keeps_only_in_set_pairs() -> None:
    """Only pruned pairs with both endpoints in the current backbone set are removed."""
    links = ForcedLinks(removed_backbone=frozenset({edge_key("P0", "P1"), edge_key("P0", "P9")}))
    assert removed_backbone_pairs({"P0", "P1"}, links) == frozenset({edge_key("P0", "P1")})


def test_forced_backbone_pairs_keeps_only_in_set_pairs() -> None:
    """Only forced pairs with both endpoints in the current backbone set are wired."""
    links = ForcedLinks(backbone=frozenset({edge_key("P0", "P1"), edge_key("P0", "P9")}))
    assert forced_backbone_pairs({"P0", "P1"}, links) == frozenset({edge_key("P0", "P1")})


def test_unknown_backbone_endpoint_is_rejected() -> None:
    """A pinned mesh endpoint absent from the Carrier graph is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(backbone=(ForcedConnection("Nowhere", "P1"),)), VERTICES, {"P1"}
        )


def test_backbone_endpoint_not_forced_is_rejected() -> None:
    """A pinned mesh endpoint that is not a forced backbone node is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(backbone=(ForcedConnection("P0", "P1"),)), VERTICES, {"P0"}
        )


def test_forced_home_target_not_forced_is_rejected() -> None:
    """A forced home's target that is not a forced backbone node is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(access=(ForcedConnection("A1", "P1"),)), VERTICES, set()
        )


def test_forced_home_source_that_is_not_demand_is_rejected() -> None:
    """A forced home's source that is not a demand vertex is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            OperatorLinks(access=(ForcedConnection("Nope", "P1"),)), VERTICES, {"P1"}
        )


def test_a_mesh_pair_is_not_read_as_a_home() -> None:
    """A pair written in the backbone list never lands among the homes.

    The tier comes from the list alone now, so nothing on the entry could redirect it --
    this is the check that the two lists stay apart rather than both feeding one set.
    """
    links = resolve_forced_links(
        OperatorLinks(backbone=(ForcedConnection("P0", "P1"),)), VERTICES, {"P0", "P1"}
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
