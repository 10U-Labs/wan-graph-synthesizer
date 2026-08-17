"""Integration test: how far a whole synthesis will route a link to make it diverse.

The unit tier can show the proof refuses a route past the operator's backup route multiple. It
cannot show the refusal survives the pipeline: peer selection, the routing heuristic that
covers every link the proof does not, and the resilience augmentation that adds detours
around cut cities all sit between a proved route and a drawn link, and any of them could
put the crossing back. So the same graph is run through the whole design here and the
routed links are asserted rather than the proof.

The first graph is ``fixtures.CROSSING_EDGES``: three sites twenty miles apart overland
through ``pdx``, and a thousand miles apart through ``tok`` offshore. Every overland route
shares ``pdx``, so the crossing is the only thing that makes a second link independent, and
a design that will buy diversity at any price takes it.

The second is ``fixtures.DISTANT_PEER_EDGES``, and it is here for the other half of the
question: whether the count and the mesh agree. The count says how many links a site should
hold and the mesh lays them, and a site credited with a route the mesh may not lay is asked
for a link nobody can wire -- a shortfall reported against the design that no cable closes.
Neither unit is wrong on its own, so only a tier holding both can see it (GitHub issue #45).

The third is ``fixtures.EXPRESS_EDGES``, and it asks how much cable the finished design
orders. Every route the proof returns is drawn span for span, so the shortest set of
independent routes only saves anything if nothing between the proof and the drawn link
lengthens it again -- peer selection, the clearing heuristic and the resilience detours all
sit in between, and the proof cannot see any of them. Here both ways of wiring the ring are
allowed by the bound and hold the same number of independent links, so the mileage is the
only thing separating them (GitHub issue #57).
"""

from __future__ import annotations

import fixtures
from synthesizer.input_graph import PhysicalEdge, Vertex
from synthesizer.model import DesignArtifacts, DesignParams, Tuning

_SEATS = 3


def _artifacts(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    datacenter_cities: frozenset[tuple[str, str]],
    multiple: float,
) -> DesignArtifacts:
    """The design the whole pipeline settles on over one graph at one backup route multiple.

    All three sites are seated, so the question is only how their links are routed and what
    each is held to. The convergence promotion is off and there are no demand vertices, so
    nothing grows the backbone past the three and the mesh is the whole of what the run
    decides.
    """
    return fixtures.run_design(
        vertices,
        physical_edges,
        DesignParams(
            min_backbone_count=_SEATS,
            max_backbone_count=_SEATS,
            datacenter_cities=datacenter_cities,
            promote_high_degree_convergences=False,
            tuning=Tuning(
                backbone_number_of_diverse_paths=2, backbone_max_backup_route_multiple=multiple
            ),
        ),
    )


def _crossing(multiple: float) -> DesignArtifacts:
    """The crossing graph at one bound, which is the only thing that varies between runs."""
    return _artifacts(
        fixtures.crossing_vertices(),
        fixtures.CROSSING_EDGES,
        fixtures.crossing_datacenter_cities(),
        multiple,
    )


BOUNDED = _crossing(3.0)
UNBOUNDED = _crossing(1000.0)
DISTANT_PEER = _artifacts(
    fixtures.distant_peer_vertices(),
    fixtures.DISTANT_PEER_EDGES,
    fixtures.distant_peer_datacenter_cities(),
    3.0,
)
EXPRESS = _artifacts(
    fixtures.express_vertices(),
    fixtures.EXPRESS_EDGES,
    fixtures.express_datacenter_cities(),
    3.0,
)


def _routed_cities(artifacts: DesignArtifacts) -> set[str]:
    """Every city the backbone's routed mesh links pass through."""
    return {
        city
        for use in artifacts.design.path_uses
        if use.purpose == "backbone_mesh"
        for city in use.path
    }


def _mesh_miles(artifacts: DesignArtifacts) -> float:
    """The cable every backbone-to-backbone link in a design runs on, added up."""
    return sum(
        use.distance_miles for use in artifacts.design.path_uses
        if use.purpose == "backbone_mesh"
    )


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


def test_no_site_is_asked_for_a_link_the_bound_will_not_let_the_mesh_lay() -> None:
    """The distant-peer design reports nobody short of their target of independent links.

    ``sea`` can hold one: both its ways out to a peer it may use run through ``pdx``, and
    the way round through ``tok`` is two thousand miles of cable to cover twenty. Asked for
    two it would be reported short for the rest of the build's life, because the link it
    was short of is one the bound itself refuses and no cable an operator buys can close it.
    """
    assert DISTANT_PEER.validation["backbone_mesh_independence_deficient"] == []


def test_the_distant_peer_ceiling_is_the_one_its_usable_fiber_carries() -> None:
    """sea is held to one link, which is what makes the assertion above worth making.

    Without this the shortfall could have gone away because the mesh found ``sea`` a second
    independent link, rather than because the count stopped asking for one it could not
    have. Reported by name because the tool lowered the target itself.
    """
    limited = {
        str(entry["id"]): entry["ceiling"]
        for entry in DISTANT_PEER.validation["backbone_diverse_paths_ceiling_limited"]
    }
    assert limited == {"sea": 1}


def test_the_finished_design_orders_the_least_cable_its_fiber_can_be_wired_with() -> None:
    """The ring design's three links run six miles in all, not the fifteen the express spans do.

    The unit tier pins what the proof hands over; this pins that the mesh lays it. Between
    the two sit the peer picks, the clearing heuristic and the resilience detours, and a
    design that proved the ring and then drew an express span anyway would cost the operator
    the whole saving while every other assertion here still passed.
    """
    assert _mesh_miles(EXPRESS) == 6.0


def test_the_ring_design_holds_every_site_to_the_two_links_its_fiber_carries() -> None:
    """Nobody comes up short, so the six miles bought the same protection fifteen would.

    Without this the assertion above would pass on a design that saved its cable by wiring
    fewer links, which is not a saving at all: a link not laid is protection not bought, and
    the point of choosing the shorter set is that it costs the site none of its routes.
    """
    assert EXPRESS.validation["backbone_mesh_independence_deficient"] == []
