"""Unit tests for the codec that loads stored simple rows into graph objects."""

from __future__ import annotations

from synthesizer.codec import _slug, load_merged_carriers, load_off_net, load_regions, load_sites
from synthesizer.model import is_carrier_pop

_MERGED_CARRIER_SITES = [
    {"carrier": "lumen", "municipality": "Denver", "state": "CO",
     "country": "United States", "latitude": 39.7392, "longitude": -104.9903},
    {"carrier": "lumen", "municipality": "Kansas City", "state": "MO",
     "country": "United States", "latitude": 39.0997, "longitude": -94.5786},
    {"carrier": "zayo", "municipality": "Denver", "state": "CO",
     "country": "United States", "latitude": 39.7392, "longitude": -104.9903},
]
_MERGED_CARRIER_LINKS = [
    {"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
     "z_municipality": "Kansas City", "z_state": "MO"},
]


def test_slug_hyphenates_punctuation() -> None:
    """Punctuation and case collapse to a hyphenated slug."""
    assert _slug("St. Louis, MO") == "st-louis-mo"


def test_slug_empty_falls_back() -> None:
    """A slug with no usable characters falls back to a placeholder."""
    assert _slug("!!!") == "x"


def test_merged_carriers_name_a_pop_by_its_city() -> None:
    """A carrier point's display name is its ``City, ST``."""
    pops, _links = load_merged_carriers(_MERGED_CARRIER_SITES, _MERGED_CARRIER_LINKS)
    assert pops[0].name == "Denver, CO"


def test_merged_carrier_points_are_carrier_pops() -> None:
    """Every merged-carrier point classifies as a carrier PoP."""
    pops, _links = load_merged_carriers(_MERGED_CARRIER_SITES, _MERGED_CARRIER_LINKS)
    assert all(is_carrier_pop(pop) for pop in pops)


def test_merged_carriers_collapse_a_city_across_carriers() -> None:
    """Colocated points from different carriers collapse to one city node."""
    pops, _links = load_merged_carriers(_MERGED_CARRIER_SITES, _MERGED_CARRIER_LINKS)
    assert {pop.id for pop in pops} == {"denver-co", "kansas-city-mo"}


def test_merged_carriers_resolve_a_segment_by_city() -> None:
    """A fiber segment resolves both endpoints to the shared city nodes."""
    _pops, links = load_merged_carriers(_MERGED_CARRIER_SITES, _MERGED_CARRIER_LINKS)
    assert list(links) == [("denver-co", "kansas-city-mo")]


def test_merged_carriers_skip_a_segment_to_an_unserved_city() -> None:
    """A fiber segment naming a city no carrier serves is dropped, not an error."""
    dangling = [{"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
                 "z_municipality": "Nowhere", "z_state": "ZZ"}]
    _pops, links = load_merged_carriers(_MERGED_CARRIER_SITES, dangling)
    assert not links


def test_merged_carriers_compute_segment_distance() -> None:
    """A fiber segment's distance is the great-circle miles between its points."""
    _pops, links = load_merged_carriers(_MERGED_CARRIER_SITES, _MERGED_CARRIER_LINKS)
    assert round(next(iter(links.values())).distance_miles) == 557


def test_merged_carriers_drop_an_isolated_point() -> None:
    """A point no surviving segment touches is dropped from the merged carriers."""
    extra = _MERGED_CARRIER_SITES + [
        {"carrier": "lumen", "municipality": "Boise", "state": "ID",
         "country": "United States", "latitude": 43.6, "longitude": -116.2},
    ]
    pops, _links = load_merged_carriers(extra, _MERGED_CARRIER_LINKS)
    assert "boise-id" not in {pop.id for pop in pops}


def test_merged_carriers_skip_an_intra_city_self_loop() -> None:
    """A fiber segment whose two endpoints are the same city is dropped, not a self-loop."""
    loop = [{"carrier": "lumen", "a_municipality": "Denver", "a_state": "CO",
             "z_municipality": "Denver", "z_state": "CO"}]
    _pops, links = load_merged_carriers(_MERGED_CARRIER_SITES, loop)
    assert not links


def test_regions_are_provider_regions() -> None:
    """Provider regions carry the provider kind so the map colours them."""
    regions = load_regions([
        {"name": "us-east-1", "municipality": "Ashburn", "state": "VA",
         "country": "United States", "latitude": 39.0, "longitude": -77.5},
    ])
    assert regions[0].kind == "provider region"


def test_sites_keep_their_given_name() -> None:
    """A tenant site is named by its ``name`` column."""
    sites = load_sites([
        {"name": "Buckley", "municipality": "Aurora", "state": "CO",
         "country": "United States", "latitude": 39.7, "longitude": -104.75},
    ])
    assert sites[0].name == "Buckley"


def test_sites_read_a_yes_exempt_column_as_exempt() -> None:
    """A ``Yes`` in the exempt column marks the site exempt from the distance constraint."""
    sites = load_sites([
        {"name": "Shafter", "municipality": "Honolulu", "state": "HI",
         "country": "United States", "latitude": 21.3, "longitude": -157.9,
         "exemptfromdistanceconstraint": "Yes"},
    ])
    assert sites[0].exempt_from_distance_constraint


def test_sites_read_a_no_exempt_column_as_not_exempt() -> None:
    """A ``No`` in the exempt column leaves the site subject to the distance constraint."""
    sites = load_sites([
        {"name": "Buckley", "municipality": "Aurora", "state": "CO",
         "country": "United States", "latitude": 39.7, "longitude": -104.75,
         "exemptfromdistanceconstraint": "No"},
    ])
    assert not sites[0].exempt_from_distance_constraint


def test_places_without_an_exempt_column_are_not_exempt() -> None:
    """A row lacking the exempt column (regions, off-net, carrier PoPs) is not exempt."""
    regions = load_regions([
        {"name": "us-east-1", "municipality": "Ashburn", "state": "VA",
         "country": "United States", "latitude": 39.0, "longitude": -77.5},
    ])
    assert not regions[0].exempt_from_distance_constraint


def test_off_net_sites_are_named_by_city() -> None:
    """Off-net candidates have no name column, so they are named by ``City, ST``."""
    off_net = load_off_net([
        {"municipality": "Dulles", "state": "VA", "country": "United States",
         "latitude": 39.0, "longitude": -77.4},
    ])
    assert off_net[0].name == "Dulles, VA"


def test_non_us_place_is_named_by_city_and_country() -> None:
    """A non-US row is named ``City, Country`` (the country replaces the blank state)."""
    off_net = load_off_net([
        {"municipality": "Tokyo", "state": "", "country": "Japan",
         "latitude": 35.6764, "longitude": 139.65},
    ])
    assert off_net[0].name == "Tokyo, Japan"


def test_repeated_names_get_distinct_ids() -> None:
    """Two places with the same name are de-duplicated into distinct ids."""
    sites = load_sites([
        {"name": "Hub", "municipality": "A", "state": "CO", "country": "United States",
         "latitude": 1.0, "longitude": 2.0},
        {"name": "Hub", "municipality": "B", "state": "CO", "country": "United States",
         "latitude": 3.0, "longitude": 4.0},
    ])
    assert [site.id for site in sites] == ["site-hub", "site-hub-2"]
