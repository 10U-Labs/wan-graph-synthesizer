"""Unit tests for population-anchored core and aggregation placement."""

from __future__ import annotations

from pathlib import Path

from wan_designer.model import Vertex, VertexInfo
from wan_designer.population import (
    Anchor,
    MunicipalityRow,
    StatePlacement,
    access_states,
    carrier_states,
    load_county_populations,
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


def placement(core: Anchor, aggregations: tuple[Anchor, ...], required: bool) -> StatePlacement:
    """Build a state placement from its core and aggregation anchors."""
    return StatePlacement(core.state, core, aggregations, required)


DENVER = muni("Denver", "CO", "Denver", 700_000)
AURORA = muni("Aurora", "CO", "Denver", 350_000)
BOULDER = muni("Boulder", "CO", "Boulder", 100_000)
CO_MUNIS = [DENVER, AURORA, BOULDER]
CO_COUNTIES = {("CO", "denver"): 1_400_000, ("CO", "boulder"): 320_000}
P1 = pop("p1", "Spur One", "CO", 39.0, -104.0)
P2 = pop("p2", "Spur Two", "CO", 40.0, -105.0)
DENVER_ANCHOR = anchor("Denver", "CO", 39.7, -104.9)


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


def test_load_county_populations_keys_by_state_and_county(tmp_path: Path) -> None:
    """County populations load keyed by state and normalized county name."""
    path = tmp_path / "counties.csv"
    path.write_text("state,county,population\nCO,Denver County,715522\n", encoding="utf-8")
    assert load_county_populations(path) == {("CO", "denver"): 715522}


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


def test_population_placements_cores_on_the_top_county_city() -> None:
    """A state's core anchor is the largest city of its most-populous county."""
    placements = population_placements([], set(), CO_COUNTIES, CO_MUNIS, {"CO"})
    assert placements[0].core.municipality == "Denver"


def test_population_placements_aggregates_top_two_county_cities() -> None:
    """Aggregations are the top cities of the two most-populous counties."""
    placements = population_placements([], set(), CO_COUNTIES, CO_MUNIS, {"CO"})
    assert tuple(a.municipality for a in placements[0].aggregations) == ("Denver", "Boulder")


def test_population_placements_requires_aggregations_for_access_state() -> None:
    """A state with access demand is flagged to require its aggregations."""
    placements = population_placements([], {"CO"}, CO_COUNTIES, CO_MUNIS, {"CO"})
    assert placements[0].requires_aggregations is True


def test_population_placements_optional_aggregations_without_access() -> None:
    """A state with no access demand does not require its aggregations."""
    placements = population_placements([], set(), CO_COUNTIES, CO_MUNIS, {"CO"})
    assert placements[0].requires_aggregations is False


def test_population_placements_reuses_a_co_located_pop() -> None:
    """An anchor whose city already hosts a PoP records that PoP for reuse."""
    pops = [pop("denver", "Denver", "CO"), pop("nomuni", "", "CO")]
    placements = population_placements(pops, set(), CO_COUNTIES, CO_MUNIS, {"CO"})
    assert placements[0].core.existing_pop_id == "denver"


def test_population_placements_anchor_without_a_pop_is_greenfield() -> None:
    """An anchor whose city hosts no PoP records no existing PoP id."""
    placements = population_placements([], set(), CO_COUNTIES, CO_MUNIS, {"CO"})
    assert placements[0].core.existing_pop_id is None


def test_population_placements_skips_a_state_without_counties() -> None:
    """A state absent from the county reference produces no placement."""
    assert population_placements([], set(), {}, CO_MUNIS, {"CO"}) == []


def test_population_placements_skips_a_county_without_municipalities() -> None:
    """A top county with no municipalities in the reference produces no placement."""
    assert population_placements([], set(), CO_COUNTIES, [], {"CO"}) == []


def test_population_placements_single_county_uses_a_second_city() -> None:
    """One populous county fills the second aggregation from its second-largest city."""
    counties = {("CO", "denver"): 1_400_000}
    placements = population_placements([], set(), counties, [DENVER, AURORA], {"CO"})
    assert tuple(a.municipality for a in placements[0].aggregations) == ("Denver", "Aurora")


def test_population_placements_single_city_county_yields_one_aggregation() -> None:
    """A lone county with a lone city can only seat one aggregation."""
    counties = {("CO", "denver"): 1_400_000}
    placements = population_placements([], set(), counties, [DENVER], {"CO"})
    assert len(placements[0].aggregations) == 1


def test_population_placements_empty_second_county_falls_back() -> None:
    """An empty second county falls back to the first county's second city."""
    placements = population_placements([], set(), CO_COUNTIES, [DENVER, AURORA], {"CO"})
    assert tuple(a.municipality for a in placements[0].aggregations) == ("Denver", "Aurora")


def test_population_placements_isolates_other_states() -> None:
    """A county in another state never influences a state's placement."""
    counties = {("CO", "denver"): 1_400_000, ("TX", "harris"): 5_000_000}
    placements = population_placements([], set(), counties, [DENVER], {"CO"})
    assert placements[0].core.municipality == "Denver"


def test_realize_anchors_reuses_an_existing_pop() -> None:
    """A reused anchor adds no vertex and resolves to the existing PoP id."""
    seated = realize_anchors(
        [placement(anchor("Denver", "CO", existing="denver"), (), False)],
        [pop("denver", "Denver", "CO")],
        {},
    )
    assert (seated.core_anchor_ids, len(seated.vertices)) == (frozenset({"denver"}), 1)


def test_realize_anchors_synthesizes_a_greenfield_vertex() -> None:
    """A PoP-less anchor appends a greenfield carrier PoP at the anchor city."""
    seated = realize_anchors([placement(DENVER_ANCHOR, (), False)], [P1, P2], {})
    greenfield = next(v for v in seated.vertices if v.id in seated.core_anchor_ids)
    assert greenfield.tenant == "Greenfield"


def test_realize_anchors_procures_links_for_a_greenfield_node() -> None:
    """A greenfield node gets to-be-procured links to each nearby PoP."""
    seated = realize_anchors([placement(DENVER_ANCHOR, (), False)], [P1, P2], {})
    assert (len(seated.vertices), len(seated.physical_edges)) == (3, 2)


def test_realize_anchors_seats_a_shared_city_once() -> None:
    """A city that is both core and aggregation is synthesized a single time."""
    seated = realize_anchors([placement(DENVER_ANCHOR, (DENVER_ANCHOR,), True)], [P1, P2], {})
    assert (seated.core_anchor_ids == seated.aggregation_anchor_ids, len(seated.vertices)) == (
        True,
        3,
    )


def test_realize_anchors_marks_required_aggregations() -> None:
    """An access state's aggregations are returned as required placements."""
    seated = realize_anchors([placement(DENVER_ANCHOR, (DENVER_ANCHOR,), True)], [P1, P2], {})
    assert seated.required_aggregation_ids == seated.aggregation_anchor_ids


def test_realize_anchors_leaves_optional_aggregations_unrequired() -> None:
    """A non-access state's aggregations are not required placements."""
    seated = realize_anchors([placement(DENVER_ANCHOR, (DENVER_ANCHOR,), False)], [P1, P2], {})
    assert seated.required_aggregation_ids == frozenset()


def test_realize_anchors_avoids_a_colliding_vertex_id() -> None:
    """A greenfield id that collides with an existing vertex id is suffixed."""
    seated = realize_anchors(
        [placement(DENVER_ANCHOR, (), False)], [pop("anchor_denver_co", "Z", "CO")], {}
    )
    assert next(iter(seated.core_anchor_ids)) == "anchor_denver_co_2"
