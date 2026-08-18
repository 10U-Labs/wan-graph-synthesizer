"""Unit tests for assembling a design from one fixed set of backbone PoPs."""

from __future__ import annotations

from dataclasses import replace

import fixtures
from fixtures import (
    TRIANGLE,
    TWO_POCKET_EDGES,
    TWO_POCKET_IDS,
    design_inputs_from_edges,
    search_plan,
)
from synthesizer.model import AccessEdge, DesignInputs, ForcedLinks
from synthesizer.assemble import (
    assign_access,
    backbone_physically_biconnectable,
    build_design_for_backbone,
    forced_backbone_resilience_error,
    nearest_pop_id,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex


def test_nearest_pop_id_picks_the_closest() -> None:
    """Nearest pop id picks the closest."""
    pops = [pop("far", 0.0, 50.0), pop("near", 0.0, 1.0)]
    assert nearest_pop_id(access("s", 0.0, 0.0), pops) == "near"


def _dual_inputs(s_coord: tuple[float, float] = (0.0, 0.05)) -> DesignInputs:
    """A two-PoP backbone with one graph-connected demand vertex ``s``."""
    return design_inputs_from_edges(
        ["c1", "c2"], DUAL_EDGES, {"c1", "c2"},
        [access("s", *s_coord)], {"c1": (0.0, 0.0), "c2": (0.0, 0.1)},
    )


def _access_link_counts(edges: list[AccessEdge]) -> dict[str, int]:
    """Number of backbone links each demand vertex received."""
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
    return counts


def test_assign_access_homes_a_demand_vertex_to_two_backbone_nodes() -> None:
    """A demand vertex homes to its two nearest backbone nodes in one pass."""
    result = assign_access(("c1", "c2"), _dual_inputs(), search_plan([]))
    assert result is not None and _access_link_counts(result) == {"s": 2}


def test_assign_access_returns_none_when_backbone_smaller_than_links() -> None:
    """With fewer backbone nodes than the homing degree, assignment fails."""
    assert assign_access(("c1",), _dual_inputs(), search_plan([], access_backbone_links=2)) is None


def test_assign_access_homes_to_the_configured_count() -> None:
    """A demand vertex homes to exactly the configured number of backbone nodes."""
    triple_edges = physical(
        {
            ("c1", "c2"): 1.0, ("c2", "c3"): 1.0, ("c1", "c3"): 1.0,
            ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("s", "c3"): 1.0,
        }
    )
    inputs = design_inputs_from_edges(
        ["c1", "c2", "c3"], triple_edges, {"c1", "c2", "c3"},
        [access("s", 0.0, 0.05)], {"c1": (0.0, 0.0), "c2": (0.0, 0.1), "c3": (0.0, 0.2)},
    )
    result = assign_access(("c1", "c2", "c3"), inputs, search_plan([], access_backbone_links=3))
    assert result is not None and _access_link_counts(result) == {"s": 3}


def test_assign_access_leads_with_a_forced_home() -> None:
    """An operator-forced access-backbone link leads a demand vertex's homes."""
    plan = replace(search_plan([]), forced_links=ForcedLinks(access=frozenset({("s", "c2")})))
    result = assign_access(("c1", "c2"), _dual_inputs((0.0, 0.0)), plan)
    assert result is not None and {edge.target for edge in result if edge.source == "s"} == {
        "c1", "c2",
    }


def test_build_design_returns_none_without_homing() -> None:
    """build_design_for_backbone returns None when the backbone is too small to home.

    With a single backbone node and a homing degree of two, no demand vertex can reach
    two distinct backbone nodes, so the design is infeasible.
    """
    inputs = _dual_inputs()
    plan = search_plan([], access_backbone_links=2)
    assert build_design_for_backbone(("c1",), inputs, plan) is None


def test_build_design_returns_none_when_nodes_are_not_meshed() -> None:
    """build_design_for_backbone returns None when a node cannot reach the others."""
    edges = physical(
        {
            ("c1", "g1"): 1.0, ("c2", "g1"): 1.0, ("c1", "g2"): 1.0, ("c2", "g2"): 1.0,
            ("c3", "z"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0,
        }
    )
    inputs = design_inputs_from_edges(
        ["c1", "c2", "c3", "g1", "g2", "z"], edges, {"c1", "c2", "c3"}, [access("s")]
    )
    assert build_design_for_backbone(("c1", "c2", "c3"), inputs, search_plan([])) is None


def test_build_design_builds_a_full_design() -> None:
    """build_design_for_backbone assembles a design when the backbone is feasible."""
    design = build_design_for_backbone(("c1", "c2"), _dual_inputs(), search_plan([]))
    assert design is not None and set(design.backbone_ids) == {"c1", "c2"}


def _two_pocket_inputs() -> DesignInputs:
    """Inputs over two fiber pockets joined by a single bridge segment."""
    return design_inputs_from_edges(TWO_POCKET_IDS, TWO_POCKET_EDGES, set(TWO_POCKET_IDS))


def _bowtie_inputs() -> DesignInputs:
    """Inputs over a bowtie: two triangles sharing one cut city."""
    return design_inputs_from_edges(_BOWTIE_IDS, _BOWTIE_EDGES, set(_BOWTIE_IDS))


def test_physically_biconnectable_within_one_block() -> None:
    """Two nodes sharing one biconnected block can be wired into a city-survivable mesh."""
    assert backbone_physically_biconnectable(("a", "b"), _two_pocket_inputs()) is True


def test_not_physically_biconnectable_across_a_bridge() -> None:
    """Two nodes split by a single segment share no block, so they are rejected."""
    assert backbone_physically_biconnectable(("a", "d"), _two_pocket_inputs()) is False


def test_not_physically_biconnectable_across_a_cut_city() -> None:
    """Two nodes either side of a cut city are rejected though no one segment splits them."""
    assert backbone_physically_biconnectable(("a", "d"), _bowtie_inputs()) is False


def test_physically_biconnectable_within_one_bowtie_lobe() -> None:
    """Two nodes in the same bowtie lobe share that lobe's block, so they pass."""
    assert backbone_physically_biconnectable(("a", "b"), _bowtie_inputs()) is True


def test_not_biconnectable_with_no_backbone_nodes() -> None:
    """An empty backbone shares no block, so the gate rejects it."""
    assert backbone_physically_biconnectable((), _bowtie_inputs()) is False


def test_forced_resilience_error_for_forced_nodes_split_across_pockets() -> None:
    """Forced nodes in different pockets can never form a resilient design."""
    assert forced_backbone_resilience_error(
        frozenset({"a", "d"}), _two_pocket_inputs(), 2
    ) is not None


def _triangle_inputs() -> DesignInputs:
    """Inputs over a single 2-edge-connected triangle pocket of three eligible PoPs."""
    return design_inputs_from_edges(["a", "b", "c"], TRIANGLE, {"a", "b", "c"})


def test_forced_resilience_error_for_a_pocket_too_small_for_the_floor() -> None:
    """A forced node whose block cannot seat the minimum backbone count is rejected.

    The forced node's pocket holds only its three triangle peers, fewer than the floor of
    five, even though other eligible nodes sit in the graph's other pocket.
    """
    assert forced_backbone_resilience_error(frozenset({"a"}), _two_pocket_inputs(), 5) is not None


def test_forced_resilience_error_none_for_a_healthy_forced_node() -> None:
    """A forced node in a pocket large enough for the floor raises nothing."""
    assert forced_backbone_resilience_error(frozenset({"a"}), _triangle_inputs(), 2) is None


def test_forced_resilience_error_none_without_forced_nodes() -> None:
    """With no forced nodes there is nothing to check, so no error."""
    assert forced_backbone_resilience_error(frozenset(), _triangle_inputs(), 2) is None


# A demand site "s" near two backbone PoPs c1 and c2 (which mesh directly). A home is
# the logical demand-to-backbone link, so "s" homes to its two nearest backbone nodes.
DUAL_EDGES = physical(
    {("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0}
)


# --- physical biconnectivity: the search-time city-survivability gate --------------------

# A bowtie -- triangles {a,b,x} and {x,d,e} sharing the cut city x. It is bridgeless (so
# 2-edge-connectable across the lobes) yet x is an articulation point: {a,d} cannot be
# made city-survivable. The case the segment gate passed but the city gate must reject.
_BOWTIE_EDGES = physical(
    {
        ("a", "b"): 1.0, ("b", "x"): 1.0, ("a", "x"): 1.0,
        ("x", "d"): 1.0, ("d", "e"): 1.0, ("x", "e"): 1.0,
    }
)
_BOWTIE_IDS = ["a", "b", "x", "d", "e"]
