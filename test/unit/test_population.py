"""Unit tests for metro-anchored core and aggregation placement."""

from __future__ import annotations

from pathlib import Path

from wan_designer.model import Vertex, VertexInfo
from wan_designer.population import (
    Anchor,
    Metro,
    MetroRef,
    MunicipalityRow,
    StatePlacement,
    _metro_city_slots,
    _state_metros,
    access_states,
    carrier_states,
    load_county_metros,
    load_municipalities,
    normalize_place,
    population_placements,
    realize_anchors,
)


def muni(name: str, state: str, county: str, population: int) -> MunicipalityRow:
    """Build a municipality reference row with a normalized county key."""
    return MunicipalityRow(name, state, normalize_place(county), population, (0.0, 0.0))


def pop(pop_id: str, municipality: str, state: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a carrier PoP carrying a serving municipality and state."""
    info = VertexInfo(municipality=municipality, state=state)
    return Vertex(pop_id, pop_id, "Lumen", "PoP", (lat, lon), info)


def access(state: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an access vertex carrying a state."""
    info = VertexInfo(state=state)
    return Vertex("access", "access", "F-35", "Military installation", (lat, lon), info)


def anchor(
    name: str, state: str, lat: float = 0.0, lon: float = 0.0, existing: str | None = None
) -> Anchor:
    """Build an anchor for a chosen city."""
    return Anchor(name, state, (lat, lon), existing)


def placement(
    core: Anchor,
    in_metro_second: Anchor | None,
    second_metro: Anchor | None,
    required: bool,
) -> StatePlacement:
    """Build a state placement from its core and two aggregation-slot anchors."""
    return StatePlacement(core.state, core, in_metro_second, second_metro, required)


# Colorado's Denver metro (Denver > Aurora) outranks its Boulder metro by official
# CBSA population; the synthetic CBSA codes and metro populations are fixture data.
DENVER = muni("Denver", "CO", "Denver", 700_000)
AURORA = muni("Aurora", "CO", "Arapahoe", 380_000)
BOULDER = muni("Boulder", "CO", "Boulder", 100_000)
CO_MUNIS = [DENVER, AURORA, BOULDER]
CO_METROS = {
    ("CO", "denver"): MetroRef("100", 3_000_000),
    ("CO", "arapahoe"): MetroRef("100", 3_000_000),
    ("CO", "boulder"): MetroRef("200", 300_000),
}
DENVER_METRO = Metro("100", 3_000_000, (DENVER, AURORA))
BOULDER_METRO = Metro("200", 300_000, (BOULDER,))
P1 = pop("p1", "Spur One", "CO", 39.0, -104.0)
P2 = pop("p2", "Spur Two", "CO", 40.0, -105.0)
DENVER_ANCHOR = anchor("Denver", "CO", 39.7, -104.9)
AURORA_ANCHOR = anchor("Aurora", "CO", 39.73, -104.83)
BOULDER_ANCHOR = anchor("Boulder", "CO", 40.0, -105.2)


def test_normalize_place_strips_a_place_designator() -> None:
    """A trailing place designator is dropped so the bare name remains."""
    assert normalize_place("Denver city") == "denver"


def test_normalize_place_strips_the_county_designator() -> None:
    """A county name loses its ``County`` designator."""
    assert normalize_place("Denver County") == "denver"


def test_normalize_place_folds_saint_to_st() -> None:
    """A spelled-out ``Saint`` folds to ``st`` to match abbreviated names."""
    assert normalize_place("Saint Louis") == "st louis"


def test_normalize_place_folds_abbreviated_saint() -> None:
    """An abbreviated ``St.`` folds to the same key as ``Saint``."""
    assert normalize_place("St. Louis") == "st louis"


def test_normalize_place_keeps_an_all_designator_name() -> None:
    """A name made only of designators keeps them rather than emptying out."""
    assert normalize_place("City") == "city"


def test_load_county_metros_keys_by_state_and_county(tmp_path: Path) -> None:
    """The CBSA crosswalk loads keyed by state and normalized county name."""
    path = tmp_path / "county_metros.csv"
    path.write_text(
        "state,county,cbsa_code,cbsa_title,cbsa_population\n"
        "CO,Denver County,19740,Denver Metro,3005131\n",
        encoding="utf-8",
    )
    assert load_county_metros(path) == {("CO", "denver"): MetroRef("19740", 3005131)}


def test_load_municipalities_parses_a_row(tmp_path: Path) -> None:
    """A municipality row loads its name, state, county key, population, and coords."""
    path = tmp_path / "municipalities.csv"
    path.write_text(
        "state,municipality,county,population,latitude,longitude\n"
        "CO,Denver,Denver County,715522,39.7392,-104.9903\n",
        encoding="utf-8",
    )
    assert load_municipalities(path)[0] == MunicipalityRow(
        "Denver", "CO", "denver", 715522, (39.7392, -104.9903)
    )


def test_carrier_states_collects_non_empty_states() -> None:
    """Carrier states are the populated states of the carrier PoPs."""
    assert carrier_states([pop("a", "Denver", "CO"), pop("b", "", "")]) == {"CO"}


def test_access_states_uses_the_access_vertex_state() -> None:
    """An access vertex contributes its own state."""
    assert access_states([access("CA")], []) == {"CA"}


def test_access_states_falls_back_to_nearest_pop_state() -> None:
    """An access vertex with no state inherits its nearest PoP's state."""
    assert access_states([access("", 39.0, -104.0)], [P1, P2]) == {"CO"}


def test_access_states_empty_without_state_or_pops() -> None:
    """A stateless access vertex with no PoPs to borrow from yields nothing."""
    assert access_states([access("")], []) == set()


def test_access_states_discards_an_empty_nearest_state() -> None:
    """A stateless access vertex near a stateless PoP contributes nothing."""
    assert access_states([access("")], [pop("p", "Nowhere", "")]) == set()


def test_state_metros_groups_municipalities_by_cbsa() -> None:
    """Municipalities sharing a CBSA join one metro, keyed by that CBSA code."""
    metros = _state_metros("CO", CO_METROS, CO_MUNIS)
    top = next(metro for metro in metros if metro.cbsa_code == "100")
    assert {row.municipality for row in top.cities} == {"Denver", "Aurora"}


def test_state_metros_ranks_by_official_cbsa_population() -> None:
    """Metros rank by their official Census population, most populous first."""
    metros = _state_metros("CO", CO_METROS, CO_MUNIS)
    assert [metro.cbsa_code for metro in metros] == ["100", "200"]


def test_state_metros_ranks_cities_within_a_metro_by_population() -> None:
    """A metro's cities are ordered by municipality population, largest first."""
    metros = _state_metros("CO", CO_METROS, CO_MUNIS)
    assert [row.municipality for row in metros[0].cities] == ["Denver", "Aurora"]


def test_state_metros_drops_municipalities_in_no_metro() -> None:
    """A municipality whose county is absent from the crosswalk joins no metro."""
    rural = muni("Lonetree", "CO", "Elbert", 500)
    cities = {row.municipality for metro in _state_metros("CO", CO_METROS, CO_MUNIS + [rural])
              for row in metro.cities}
    assert "Lonetree" not in cities


def test_state_metros_isolates_other_states() -> None:
    """A municipality in another state never enters this state's metros."""
    other = muni("Wichita", "KS", "Sedgwick", 390_000)
    metros = _state_metros("CO", CO_METROS, CO_MUNIS + [other])
    assert all(row.state == "CO" for metro in metros for row in metro.cities)


def test_metro_city_slots_two_metros_fill_all_three_slots() -> None:
    """Two metros yield core, in-metro second, and second-metro distinctly."""
    core, in_metro_second, second_metro = _metro_city_slots([DENVER_METRO, BOULDER_METRO])
    assert (core, in_metro_second, second_metro) == (DENVER, AURORA, BOULDER)


def test_metro_city_slots_single_metro_two_cities_reuses_second_city() -> None:
    """One metro with two cities seats both aggregation slots on its second city."""
    _core, in_metro_second, second_metro = _metro_city_slots([DENVER_METRO])
    assert (in_metro_second, second_metro) == (AURORA, AURORA)


def test_metro_city_slots_single_metro_single_city_has_no_aggregations() -> None:
    """One metro with one city fills neither aggregation slot."""
    _core, in_metro_second, second_metro = _metro_city_slots([Metro("100", 3_000_000, (DENVER,))])
    assert (in_metro_second, second_metro) == (None, None)


def test_metro_city_slots_thin_first_metro_falls_back_to_second_metro() -> None:
    """A single-city first metro draws its in-metro second from the second metro."""
    thin_first = Metro("100", 3_000_000, (DENVER,))
    _core, in_metro_second, second_metro = _metro_city_slots([thin_first, BOULDER_METRO])
    assert (in_metro_second, second_metro) == (BOULDER, BOULDER)


def test_population_placements_cores_on_top_metro_top_city() -> None:
    """A state's core anchor is the largest city of its most-populous metro."""
    placements = population_placements([], set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].core.municipality == "Denver"


def test_population_placements_in_metro_second_is_the_metros_second_city() -> None:
    """The cored first aggregation is the second city of the most-populous metro."""
    placements = population_placements([], set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].in_metro_second.municipality == "Aurora"


def test_population_placements_second_metro_is_the_next_metros_top_city() -> None:
    """The second aggregation is the top city of the second-most-populous metro."""
    placements = population_placements([], set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].second_metro.municipality == "Boulder"


def test_population_placements_requires_aggregations_for_access_state() -> None:
    """A state with access demand is flagged to require its aggregations."""
    placements = population_placements([], {"CO"}, CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].requires_aggregations is True


def test_population_placements_optional_aggregations_without_access() -> None:
    """A state with no access demand does not require its aggregations."""
    placements = population_placements([], set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].requires_aggregations is False


def test_population_placements_reuses_a_co_located_pop() -> None:
    """An anchor whose city already hosts a PoP records that PoP for reuse."""
    pops = [pop("denver", "Denver", "CO"), pop("nomuni", "", "CO")]
    placements = population_placements(pops, set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].core.existing_pop_id == "denver"


def test_population_placements_anchor_without_a_pop_is_greenfield() -> None:
    """An anchor whose city hosts no PoP records no existing PoP id."""
    placements = population_placements([], set(), CO_METROS, CO_MUNIS, {"CO"})
    assert placements[0].core.existing_pop_id is None


def test_population_placements_skips_a_state_without_metros() -> None:
    """A state absent from the metro crosswalk produces no placement."""
    assert not population_placements([], set(), {}, CO_MUNIS, {"CO"})


def test_population_placements_skips_a_state_without_municipalities() -> None:
    """A state with no municipalities in the reference produces no placement."""
    assert not population_placements([], set(), CO_METROS, [], {"CO"})


def test_population_placements_isolates_other_states() -> None:
    """A metro in another state never influences a state's placement."""
    metros = {**CO_METROS, ("TX", "harris"): MetroRef("300", 7_000_000)}
    placements = population_placements([], set(), metros, CO_MUNIS, {"CO"})
    assert placements[0].core.municipality == "Denver"


def test_realize_anchors_reuses_an_existing_pop() -> None:
    """A reused anchor adds no vertex and resolves to the existing PoP id."""
    seated = realize_anchors(
        [placement(anchor("Denver", "CO", existing="denver"), None, None, False)],
        [pop("denver", "Denver", "CO")],
        {},
    )
    assert (seated.core_anchor_ids, len(seated.vertices)) == (frozenset({"denver"}), 1)


def test_realize_anchors_synthesizes_a_greenfield_vertex() -> None:
    """A PoP-less anchor appends a greenfield carrier PoP at the anchor city."""
    seated = realize_anchors([placement(DENVER_ANCHOR, None, None, False)], [P1, P2], {})
    greenfield = next(v for v in seated.vertices if v.id in seated.core_anchor_ids)
    assert greenfield.tenant == "Greenfield"


def test_realize_anchors_procures_links_for_a_greenfield_node() -> None:
    """A greenfield node gets to-be-procured links to each nearby PoP."""
    seated = realize_anchors([placement(DENVER_ANCHOR, None, None, False)], [P1, P2], {})
    assert (len(seated.vertices), len(seated.physical_edges)) == (3, 2)


def test_realize_anchors_builds_one_spec_per_access_state() -> None:
    """Only an access-bearing state contributes an aggregation spec."""
    cored = realize_anchors(
        [placement(DENVER_ANCHOR, AURORA_ANCHOR, BOULDER_ANCHOR, True)], [P1, P2], {}
    )
    uncored = realize_anchors(
        [placement(DENVER_ANCHOR, AURORA_ANCHOR, BOULDER_ANCHOR, False)], [P1, P2], {}
    )
    assert (len(cored.aggregation_specs), len(uncored.aggregation_specs)) == (1, 0)


def test_realize_anchors_spec_carries_three_distinct_slot_ids() -> None:
    """An access state's spec records its core, in-metro, and second-metro ids."""
    seated = realize_anchors(
        [placement(DENVER_ANCHOR, AURORA_ANCHOR, BOULDER_ANCHOR, True)], [P1, P2], {}
    )
    spec = seated.aggregation_specs[0]
    ids = {spec.core_id, spec.in_metro_second_id, spec.second_metro_id}
    assert spec.core_id in seated.core_anchor_ids and len(ids) == 3


def test_realize_anchors_candidate_ids_union_every_slot() -> None:
    """The candidate union is exactly the access state's three slot ids."""
    seated = realize_anchors(
        [placement(DENVER_ANCHOR, AURORA_ANCHOR, BOULDER_ANCHOR, True)], [P1, P2], {}
    )
    spec = seated.aggregation_specs[0]
    assert seated.aggregation_candidate_ids == frozenset(
        {spec.core_id, spec.in_metro_second_id, spec.second_metro_id}
    )


def test_realize_anchors_thin_state_spec_has_none_slots() -> None:
    """A thin access state seats only its core city and leaves the slots empty."""
    seated = realize_anchors([placement(DENVER_ANCHOR, None, None, True)], [P1, P2], {})
    spec = seated.aggregation_specs[0]
    assert (spec.in_metro_second_id, spec.second_metro_id) == (None, None)
    assert seated.aggregation_candidate_ids == frozenset({spec.core_id})


def test_realize_anchors_seats_a_shared_city_once() -> None:
    """When both aggregation slots name the same city it is synthesized once."""
    seated = realize_anchors(
        [placement(DENVER_ANCHOR, AURORA_ANCHOR, AURORA_ANCHOR, True)], [P1, P2], {}
    )
    spec = seated.aggregation_specs[0]
    assert spec.in_metro_second_id == spec.second_metro_id
    assert len(seated.vertices) == 4  # P1, P2, greenfield Denver, greenfield Aurora


def test_realize_anchors_avoids_a_colliding_vertex_id() -> None:
    """A greenfield id that collides with an existing vertex id is suffixed."""
    seated = realize_anchors(
        [placement(DENVER_ANCHOR, None, None, False)], [pop("anchor_denver_co", "Z", "CO")], {}
    )
    assert next(iter(seated.core_anchor_ids)) == "anchor_denver_co_2"
