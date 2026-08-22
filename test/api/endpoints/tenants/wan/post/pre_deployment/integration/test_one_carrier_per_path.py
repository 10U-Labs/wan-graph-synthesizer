from __future__ import annotations

import fixtures
from synthesizer.input_graph import carriers_along
from synthesizer.model import SynthesisPath

_SHORTCUT_CITY = "t"
_SITES = ("a", "b", "c", "d")
ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    _SITES,
    {
        ("a", "b"): (100.0, ("lumen",)),
        ("b", "c"): (100.0, ("lumen",)),
        ("c", "d"): (100.0, ("zayo",)),
        ("d", "a"): (100.0, ("zayo",)),
        ("a", _SHORTCUT_CITY): (10.0, ("lumen",)),
        (_SHORTCUT_CITY, "c"): (10.0, ("zayo",)),
    },
    2,
    transit_ids=(_SHORTCUT_CITY,),
)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def _paths_at(site: str) -> list[SynthesisPath]:
    return [use for use in _MESH if site in (use.source, use.target)]


def _carriers_at(site: str) -> set[str]:
    return {use.carrier for use in _paths_at(site)}


def test_every_drawn_path_is_one_carriers_to_sell() -> None:
    assert all(carriers_along(use.path, ARTIFACTS.fiber_segments) for use in _MESH)


def test_every_drawn_path_names_the_carrier_it_is_ordered_from() -> None:
    assert all(use.carrier in ("lumen", "zayo") for use in _MESH)


def test_the_short_way_that_changes_hands_is_not_drawn() -> None:
    assert not [use for use in _MESH if _SHORTCUT_CITY in use.path]


def test_a_sites_ways_out_may_be_ordered_from_different_carriers() -> None:
    assert _carriers_at("a") == {"lumen", "zayo"}


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    assert all(len(_paths_at(site)) == 2 for site in _SITES)
