"""Integration test: every path a whole synthesis draws is one carrier's to sell.

A path is one thing an operator orders, from one company, and pays for every month. Half
of Lumen's Denver to Salt Lake City and half of Zayo's Salt Lake City to Reno is not a
product anybody quotes, so a synthesis that draws one has handed its tenant a network they
cannot buy. That is the defect GitHub issue #106 is about, and this is the whole pipeline
run over fiber that says who owns it.

The map is a square of four sites on hundred-mile sides, two of them Lumen's and two
Zayo's, with a shortcut across the middle through a fifth city no provider has a cage in.
The shortcut is the case: it is ten miles each side against a hundred, so it is far and
away the cheapest way from ``a`` to ``c`` and any synthesis blind to ownership takes it --
and its two halves belong to different companies, so there is nobody to buy it from. What
is left when it is refused is the square, whose two sides out of ``a`` come from two
different carriers, which is what an operator really does: one path from each of two
companies rather than one path from neither.
"""

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
    """The ways out one site is drawn with."""
    return [use for use in _MESH if site in (use.source, use.target)]


def _carriers_at(site: str) -> set[str]:
    """The carriers the ways out of one site are ordered from."""
    return {use.carrier for use in _paths_at(site)}


def test_every_drawn_path_is_one_carriers_to_sell() -> None:
    """No path in the finished synthesis changes hands partway along it."""
    assert all(carriers_along(use.path, ARTIFACTS.fiber_segments) for use in _MESH)


def test_every_drawn_path_names_the_carrier_it_is_ordered_from() -> None:
    """A tenant reading their network can see who to call for each path in it."""
    assert all(use.carrier in ("lumen", "zayo") for use in _MESH)


def test_the_cheap_way_that_changes_hands_is_not_drawn() -> None:
    """Twenty miles beats two hundred, and it is still not a path anybody sells."""
    assert not [use for use in _MESH if _SHORTCUT_CITY in use.path]


def test_a_sites_ways_out_may_be_bought_from_different_carriers() -> None:
    """Diverse paths are diverse fiber, not one supplier: a buys one path from each."""
    assert _carriers_at("a") == {"lumen", "zayo"}


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    """Refusing the shortcut costs nobody a way out; the square answers all four sites."""
    assert all(len(_paths_at(site)) == 2 for site in _SITES)
