"""Integration test: how far a whole synthesis will route a link to make it diverse.

The unit tier can show the proof refuses a route past the operator's stretch bound. It
cannot show the refusal survives the pipeline: peer selection, the routing heuristic that
covers every link the proof does not, and the resilience augmentation that adds detours
around cut cities all sit between a proved route and a drawn link, and any of them could
put the crossing back. So the same graph is run through the whole design here and the
routed links are asserted rather than the proof.

The graph is ``fixtures.CROSSING_EDGES``: three sites twenty miles apart overland through
``pdx``, and a thousand miles apart through ``tok`` offshore. Every overland route shares
``pdx``, so the crossing is the only thing that makes a second link independent, and a
design that will buy diversity at any price takes it.
"""

from __future__ import annotations

import fixtures
from synthesizer.model import DesignParams, Tuning

_SEATS = 3


def _artifacts(stretch: float) -> fixtures.DesignArtifacts:
    """The design the whole pipeline settles on at one stretch bound.

    All three sites are seated, so the question is only how their links are routed. The
    convergence promotion is off and there are no demand vertices, so nothing grows the
    backbone past the three and the mesh is the whole of what the run decides.
    """
    return fixtures.run_design(
        fixtures.crossing_vertices(),
        fixtures.CROSSING_EDGES,
        DesignParams(
            min_backbone_count=_SEATS,
            max_backbone_count=_SEATS,
            datacenter_cities=fixtures.crossing_datacenter_cities(),
            promote_high_degree_convergences=False,
            tuning=Tuning(
                backbone_number_of_diverse_paths=2, backbone_max_path_stretch=stretch
            ),
        ),
    )


BOUNDED = _artifacts(3.0)
UNBOUNDED = _artifacts(1000.0)


def _routed_cities(artifacts: fixtures.DesignArtifacts) -> set[str]:
    """Every city the backbone's routed mesh links pass through."""
    return {
        city
        for use in artifacts.design.path_uses
        if use.purpose == "backbone_mesh"
        for city in use.path
    }


def test_the_bounded_design_routes_no_link_through_the_crossing() -> None:
    """No mesh link reaches tok, though taking it is the only way to a second diverse path."""
    assert "tok" not in _routed_cities(BOUNDED)


def test_a_bound_wide_enough_still_takes_the_crossing() -> None:
    """The crossing is refused for its length and nothing else, which this pins down.

    Without it the first assertion would pass just as well on a graph the pipeline never
    routes through tok for some unrelated reason, and the test would prove nothing about
    the bound.
    """
    assert "tok" in _routed_cities(UNBOUNDED)


def test_the_bounded_design_still_wires_every_site_into_one_backbone() -> None:
    """Refusing the crossing leaves a connected mesh, not a backbone in pieces."""
    assert BOUNDED.validation["connected"]


def test_the_bounded_ceiling_is_the_honest_one() -> None:
    """sea is held to the one link its usable fiber carries, not the two the crossing offered.

    The ceiling feeds site selection as well as routing, so a fix that stopped the crossing
    being routed but left it counted would still credit sites with protection they cannot
    deliver. Reported by name because the tool lowered the target itself.
    """
    limited = {
        str(entry["id"]): entry["ceiling"]
        for entry in BOUNDED.validation["backbone_diverse_paths_ceiling_limited"]
    }
    assert limited == {"eug": 1, "hil": 1, "sea": 1}


def test_the_unbounded_ceiling_counts_the_crossing() -> None:
    """With the bound wide open every site scores its full two, which is the inflation."""
    assert UNBOUNDED.validation["backbone_diverse_paths_ceiling_limited"] == []
