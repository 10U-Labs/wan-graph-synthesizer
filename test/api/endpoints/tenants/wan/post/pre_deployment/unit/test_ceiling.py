"""Unit tests for how many independent links a backbone node's fiber can carry.

Each substrate here is built so the answer is countable by eye, because the ceiling is
what both selection and validation are then held to: it decides how many links a node
reaches for and how many it is asked for. A wrong ceiling would move both at once.
"""

from __future__ import annotations

import fixtures
from synthesizer.ceiling import (
    independent_route_ceiling,
    independent_routes,
    mesh_degree_ceilings,
)
from synthesizer.graphs import build_adjacency

physical = fixtures.physical_edges_from


# Boston in miniature: three fiber spans leave ``bos``, but every route to the rest of
# the backbone crosses ``alb`` or ``stm`` -- the third span doubles back to ``alb``. So
# the fiber degree is three and the ceiling is two, which is the distinction the number
# exists to draw.
_TWO_CUTS = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "stm"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("stm", "n2"): 1.0, ("n1", "n2"): 1.0,
}))
_TWO_CUT_BACKBONE = ("bos", "n1", "n2")


def test_the_ceiling_is_the_number_of_cuts_not_of_fiber_spans() -> None:
    """Three spans leave bos, but all routes cross alb or stm, so its ceiling is two."""
    assert independent_route_ceiling("bos", _TWO_CUT_BACKBONE, _TWO_CUTS) == 2


# The same shape with one chokepoint instead of two: every route out of ``bos`` crosses
# ``alb``, including the one that leaves on a span of its own and doubles back.
_ONE_CUT = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("alb", "n2"): 1.0, ("n1", "n2"): 1.0,
}))


def test_a_node_behind_one_chokepoint_has_a_ceiling_of_one() -> None:
    """Two spans leave bos and both routes cross alb, so one city takes everything."""
    assert independent_route_ceiling("bos", ("bos", "n1", "n2"), _ONE_CUT) == 1


# Two internally-disjoint routes from ``s`` reach the same peer ``t``, and the only other
# backbone node sits behind ``t``. Both routes die when t's city does, so together they
# are one independent link rather than two.
_TWIN_ROUTES = build_adjacency(physical({
    ("s", "p1"): 1.0, ("s", "p2"): 1.0, ("p1", "t"): 1.0, ("p2", "t"): 1.0,
    ("t", "u"): 1.0,
}))


def test_two_routes_to_one_peer_count_once() -> None:
    """Disjoint routes to the same peer both fail with that peer, so the ceiling is one."""
    assert independent_route_ceiling("s", ("s", "t", "u"), _TWIN_ROUTES) == 1


def test_an_unreachable_node_has_no_ceiling_at_all() -> None:
    """A node the substrate does not carry can hold no link, so its ceiling is zero."""
    assert independent_route_ceiling("nowhere", ("nowhere", "n1", "n2"), _ONE_CUT) == 0


def test_the_ceilings_are_computed_for_every_backbone_node() -> None:
    """The per-node pass answers for each backbone node, not just the one asked about."""
    assert mesh_degree_ceilings(_TWO_CUT_BACKBONE, _TWO_CUTS) == {"bos": 2, "n1": 2, "n2": 2}


# The count is only ever as good as the routes behind it, and something has to be able to
# wire them: a node the mesh leaves short is repaired by taking the very routes counted
# here, so these check the count can be shown its working rather than only asserted.
_BOS_ROUTES = independent_routes("bos", _TWO_CUT_BACKBONE, _TWO_CUTS)


def test_the_counted_routes_run_from_the_node_to_distinct_peers() -> None:
    """Each counted route is one link, so they leave bos and land on a peer apiece."""
    assert sorted((route[0], route[-1]) for route in _BOS_ROUTES) == [
        ("bos", "n1"), ("bos", "n2")
    ]


def test_the_counted_routes_share_no_intermediate_city() -> None:
    """No city carries two of them, which is the whole of what independence means."""
    inner = [city for route in _BOS_ROUTES for city in route[1:-1]]
    assert sorted(inner) == sorted(set(inner))
