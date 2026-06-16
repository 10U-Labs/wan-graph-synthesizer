"""Unit tests for operator-forced connections: resolution and routing wiring.

These pin the mechanism -- names resolve to id-typed links against the seated
tiers, and the optimizer honors them -- rather than any particular city pin.
"""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.forced import apply_forced_access_homes, forced_cores_for_aggregation
from wan_designer.model import ForcedConnection, ForcedLinks, edge_key
from wan_designer.overrides import resolve_forced_links

pop = fixtures.carrier_pop
access = fixtures.access_vertex

# Two carrier PoPs and one access vertex; names equal ids for the ring factories.
VERTICES = [pop("P0"), pop("P1"), access("A1")]


def test_core_core_link_resolves_to_an_edge_key() -> None:
    """A core-core connection between two forced cores resolves to their edge key."""
    links = resolve_forced_links(
        (ForcedConnection("core-core", "P0", "P1"),), VERTICES, {"P0", "P1"}, set()
    )
    assert links.core == frozenset({edge_key("P0", "P1")})


def test_aggregation_core_link_resolves_to_a_pair() -> None:
    """An aggregation-core connection resolves to an (aggregation, core) id pair."""
    links = resolve_forced_links(
        (ForcedConnection("aggregation-core", "P1", "P0"),), VERTICES, {"P0"}, {"P1"}
    )
    assert links.aggregation == frozenset({("P1", "P0")})


def test_access_aggregation_link_resolves_to_a_pair() -> None:
    """An access-aggregation connection resolves to an (access, aggregation) id pair."""
    links = resolve_forced_links(
        (ForcedConnection("access-aggregation", "A1", "P1"),), VERTICES, set(), {"P1"}
    )
    assert links.access == frozenset({("A1", "P1")})


def test_colocated_aggregation_endpoint_resolves_to_its_twin() -> None:
    """A co-located forced core forced as an aggregation resolves to its AGGR twin id."""
    links = resolve_forced_links(
        (ForcedConnection("aggregation-core", "P0", "P1"),),
        VERTICES, {"P0", "P1"}, {"aggr_P0"},
    )
    assert links.aggregation == frozenset({("aggr_P0", "P1")})


def test_unknown_core_endpoint_is_rejected() -> None:
    """A core endpoint absent from the Carrier graph is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            (ForcedConnection("core-core", "Nowhere", "P1"),), VERTICES, {"P1"}, set()
        )


def test_core_endpoint_not_forced_as_core_is_rejected() -> None:
    """A core-core endpoint that is not a forced core is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            (ForcedConnection("core-core", "P0", "P1"),), VERTICES, {"P0"}, set()
        )


def test_unknown_aggregation_endpoint_is_rejected() -> None:
    """An aggregation endpoint absent from the Carrier graph is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            (ForcedConnection("aggregation-core", "Nowhere", "P0"),), VERTICES, {"P0"}, set()
        )


def test_aggregation_endpoint_not_forced_is_rejected() -> None:
    """An aggregation-core source that is not a forced aggregation is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            (ForcedConnection("aggregation-core", "P1", "P0"),), VERTICES, {"P0"}, set()
        )


def test_unknown_access_endpoint_is_rejected() -> None:
    """An access-aggregation source that is not an access vertex is rejected."""
    with pytest.raises(ValueError):
        resolve_forced_links(
            (ForcedConnection("access-aggregation", "Nope", "P1"),), VERTICES, set(), {"P1"}
        )


def test_forced_cores_for_aggregation_keeps_only_in_set_targets() -> None:
    """Only forced cores that are in the current core set are required for an aggregation."""
    links = ForcedLinks(aggregation=frozenset({("P3", "P0"), ("P3", "P9"), ("PX", "P0")}))
    assert forced_cores_for_aggregation("P3", {"P0", "P1"}, links) == frozenset({"P0"})


def test_forced_access_home_is_pinned_over_a_nearer_facility() -> None:
    """A forced access link pins its aggregation as one of the two homes."""
    links = ForcedLinks(access=frozenset({("A1", "P3")}))
    pop_by_id = {
        "P0": pop("P0", 40.0, -100.1),
        "P1": pop("P1", 50.0, -100.0),
        "P3": pop("P3", 41.0, -99.0),
    }
    homes = apply_forced_access_homes(access("A1", 40.0, -100.0), ["P0", "P1"], links, pop_by_id)
    assert set(homes) == {"P3", "P0"}
