"""Unit tests for the codec that loads stored simple rows into graph objects."""

from __future__ import annotations

from wan_graph.codec import _slug, load_off_net, load_regions, load_sites, load_substrate
from wan_synthesizer.model import is_carrier_pop

_SUBSTRATE_VERTICES = [
    {"carrier": "lumen", "municipality": "Denver", "state": "CO",
     "latitude": 39.7392, "longitude": -104.9903},
    {"carrier": "lumen", "municipality": "Kansas City", "state": "MO",
     "latitude": 39.0997, "longitude": -94.5786},
    {"carrier": "zayo", "municipality": "Denver", "state": "CO",
     "latitude": 39.7392, "longitude": -104.9903},
]
_SUBSTRATE_EDGES = [
    {"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
     "z_municipality": "Kansas City", "z_state": "MO"},
]


def test_slug_hyphenates_punctuation() -> None:
    """Punctuation and case collapse to a hyphenated slug."""
    assert _slug("St. Louis, MO") == "st-louis-mo"


def test_slug_empty_falls_back() -> None:
    """A slug with no usable characters falls back to a placeholder."""
    assert _slug("!!!") == "x"


def test_substrate_names_a_pop_by_its_city() -> None:
    """A carrier point's display name is its ``City, ST``."""
    pops, _edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert pops[0].name == "Denver, CO"


def test_substrate_points_are_carrier_pops() -> None:
    """Every substrate point classifies as a carrier PoP."""
    pops, _edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert all(is_carrier_pop(pop) for pop in pops)


def test_substrate_points_are_not_shown_on_the_map() -> None:
    """Carrier points are backbone infrastructure, not drawn on the map."""
    pops, _edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert not any(pop.shown_in_map for pop in pops)


def test_substrate_collapses_a_city_across_carriers() -> None:
    """Colocated points from different carriers collapse to one city node."""
    pops, _edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert {pop.id for pop in pops} == {"denver-co", "kansas-city-mo"}


def test_substrate_resolves_a_connection_by_city() -> None:
    """A connection resolves both endpoints to the shared city nodes."""
    _pops, edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert list(edges) == [("denver-co", "kansas-city-mo")]


def test_substrate_skips_a_connection_to_an_unserved_city() -> None:
    """A connection to a city no carrier serves is dropped, not an error."""
    dangling = [{"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
                 "z_municipality": "Nowhere", "z_state": "ZZ"}]
    _pops, edges = load_substrate(_SUBSTRATE_VERTICES, dangling)
    assert not edges


def test_substrate_computes_connection_distance() -> None:
    """A connection's distance is the great-circle miles between its points."""
    _pops, edges = load_substrate(_SUBSTRATE_VERTICES, _SUBSTRATE_EDGES)
    assert round(next(iter(edges.values())).distance_miles) == 557


def test_substrate_drops_an_isolated_point() -> None:
    """A point no surviving connection touches is dropped from the substrate."""
    extra = _SUBSTRATE_VERTICES + [
        {"carrier": "lumen", "municipality": "Boise", "state": "ID",
         "latitude": 43.6, "longitude": -116.2},
    ]
    pops, _edges = load_substrate(extra, _SUBSTRATE_EDGES)
    assert "boise-id" not in {pop.id for pop in pops}


def test_substrate_skips_an_intra_city_self_loop() -> None:
    """A connection whose two endpoints are the same city is dropped, not a self-loop."""
    loop = [{"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
             "z_municipality": "Denver", "z_state": "CO"}]
    _pops, edges = load_substrate(_SUBSTRATE_VERTICES, loop)
    assert not edges


def test_regions_are_cloud_data_centers() -> None:
    """Cloud regions carry the CSP kind so the map colours them."""
    regions = load_regions([
        {"name": "us-east-1", "municipality": "Ashburn", "state": "VA",
         "latitude": 39.0, "longitude": -77.5},
    ])
    assert regions[0].kind == "CSP data center"


def test_sites_keep_their_given_name() -> None:
    """A tenant site is named by its ``name`` column."""
    sites = load_sites([
        {"name": "Buckley", "municipality": "Aurora", "state": "CO",
         "latitude": 39.7, "longitude": -104.75},
    ])
    assert sites[0].name == "Buckley"


def test_off_net_sites_are_named_by_city() -> None:
    """Off-net candidates have no name column, so they are named by ``City, ST``."""
    off_net = load_off_net([
        {"municipality": "Dulles", "state": "VA", "latitude": 39.0, "longitude": -77.4},
    ])
    assert off_net[0].name == "Dulles, VA"


def test_repeated_names_get_distinct_ids() -> None:
    """Two places with the same name are de-duplicated into distinct ids."""
    sites = load_sites([
        {"name": "Hub", "municipality": "A", "state": "CO", "latitude": 1.0, "longitude": 2.0},
        {"name": "Hub", "municipality": "B", "state": "CO", "latitude": 3.0, "longitude": 4.0},
    ])
    assert [site.id for site in sites] == ["site-hub", "site-hub-2"]
