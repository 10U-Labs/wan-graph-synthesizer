from __future__ import annotations

import fixtures
from synthesizer.ceiling import (
    PathProofInputs,
    independent_path_ceiling,
    independent_paths,
    diverse_path_ceilings,
)
from synthesizer.graphs import adjacency_by_carrier, build_adjacency
from synthesizer.input_graph import FiberSegment

physical = fixtures.fiber_segments_from


def _path_miles(
    path: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    return sum(
        weight
        for left, right in zip(path, path[1:])
        for neighbor, weight in adjacency[left]
        if neighbor == right
    )


_TWO_CUTS = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "stm"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("stm", "n2"): 1.0, ("n1", "n2"): 1.0,
}))
_TWO_CUT_BACKBONE = ("bos", "n1", "n2")


def test_the_ceiling_is_the_number_of_cuts_not_of_fiber_segments() -> None:
    assert independent_path_ceiling("bos", PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS)) == 2


_ONE_CUT = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("alb", "n2"): 1.0, ("n1", "n2"): 1.0,
}))


def test_a_node_behind_one_failure_point_has_a_ceiling_of_one() -> None:
    assert independent_path_ceiling("bos", PathProofInputs(("bos", "n1", "n2"), _ONE_CUT)) == 1


_TWIN_PATHS = build_adjacency(physical({
    ("s", "p1"): 1.0, ("s", "p2"): 1.0, ("p1", "t"): 1.0, ("p2", "t"): 1.0,
    ("t", "u"): 1.0,
}))


def test_two_paths_to_one_peer_count_once() -> None:
    assert independent_path_ceiling("s", PathProofInputs(("s", "t", "u"), _TWIN_PATHS)) == 1


_ONE_PEER = ("s", "t")


def test_a_site_with_one_peer_holds_the_paths_it_was_asked_for() -> None:
    inputs = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2)
    assert independent_path_ceiling("s", inputs) == 2


def test_the_paths_to_one_peer_share_no_city_but_that_peer() -> None:
    inner = [
        city
        for path in independent_paths("s", PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2))
        for city in path[1:-1]
    ]
    assert sorted(inner) == sorted(set(inner))


def test_a_site_with_one_peer_is_still_held_to_one_path_when_one_is_asked() -> None:
    inputs = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=1)
    assert independent_path_ceiling("s", inputs) == 1


def test_a_site_seated_below_the_seats_its_config_allows_takes_one_path_to_a_peer() -> None:
    ground = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2, seat_cap=6)
    assert independent_path_ceiling("s", ground) == 1


_THREE_WAYS = build_adjacency(physical({
    ("s", "near"): 1.0, ("near", "t"): 1.0,
    ("s", "mid"): 2.0, ("mid", "t"): 2.0,
    ("s", "far"): 3.0, ("far", "t"): 3.0,
}))


def test_no_more_paths_to_one_peer_are_proved_than_were_asked_for() -> None:
    inputs = PathProofInputs(_ONE_PEER, _THREE_WAYS, paths_wanted=2)
    assert independent_path_ceiling("s", inputs) == 2


def test_the_paths_proved_to_one_peer_are_the_shortest_of_them() -> None:
    paths = independent_paths("s", PathProofInputs(_ONE_PEER, _THREE_WAYS, paths_wanted=2))
    assert sorted(path[1] for path in paths) == ["mid", "near"]


def test_an_unreachable_node_has_no_ceiling_at_all() -> None:
    inputs = PathProofInputs(("nowhere", "n1", "n2"), _ONE_CUT)
    assert independent_path_ceiling("nowhere", inputs) == 0


def test_the_ceilings_are_computed_for_every_backbone_node() -> None:
    assert diverse_path_ceilings(PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS)) == {
        "bos": 2, "n1": 2, "n2": 2
    }


_BOS_PATHS = independent_paths("bos", PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS))


def test_the_counted_paths_run_from_the_node_to_distinct_peers() -> None:
    assert sorted((path[0], path[-1]) for path in _BOS_PATHS) == [
        ("bos", "n1"), ("bos", "n2")
    ]


def test_the_counted_paths_share_no_intermediate_city() -> None:
    inner = [city for path in _BOS_PATHS for city in path[1:-1]]
    assert sorted(inner) == sorted(set(inner))


_EXPRESS_SEGMENTS = build_adjacency(physical({
    ("sea", "hil"): 100.0, ("sea", "eug"): 100.0,
    ("sea", "pdx"): 1.0, ("pdx", "hil"): 1.0,
    ("sea", "tac"): 1.0, ("tac", "eug"): 1.0,
}))
_EXPRESS_BACKBONE = ("eug", "hil", "sea")


def test_the_paths_proved_are_the_shortest_set_of_that_size() -> None:
    assert sum(
        _path_miles(path, _EXPRESS_SEGMENTS)
        for path in independent_paths("sea", PathProofInputs(_EXPRESS_BACKBONE, _EXPRESS_SEGMENTS))
    ) == 4.0


def test_taking_the_shortest_set_costs_the_site_none_of_its_paths() -> None:
    inputs = PathProofInputs(_EXPRESS_BACKBONE, _EXPRESS_SEGMENTS)
    assert independent_path_ceiling("sea", inputs) == 2


_PACIFIC_ADJACENCY = build_adjacency(physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0, ("tok", "eug"): 1000.0,
}))
_PACIFIC_BACKBONE = ("eug", "hil", "sea")


def test_a_ceiling_counts_a_way_out_however_far_it_runs() -> None:
    assert independent_path_ceiling(
        "sea", PathProofInputs(_PACIFIC_BACKBONE, _PACIFIC_ADJACENCY)
    ) == 2


_CHANGES_HANDS = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen",)),
    ("x", "t"): (1.0, ("zayo",)),
    ("s", "y"): (1.0, ("lumen",)),
    ("y", "t"): (1.0, ("zayo",)),
})
_ONE_COMPANY_EACH = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen",)),
    ("x", "t"): (1.0, ("lumen",)),
    ("s", "y"): (1.0, ("zayo",)),
    ("y", "t"): (1.0, ("zayo",)),
})


def _owned_proof(
    fiber: dict[tuple[str, str], FiberSegment], paths_wanted: int = 1
) -> PathProofInputs:
    return PathProofInputs(
        ("s", "t"),
        build_adjacency(fiber),
        paths_wanted=paths_wanted,
        fiber_by_carrier=adjacency_by_carrier(fiber),
    )


def test_a_way_out_that_changes_hands_is_no_way_out() -> None:
    assert not independent_paths("s", _owned_proof(_CHANGES_HANDS))


def test_ways_out_may_come_from_different_carriers() -> None:
    assert sorted(independent_paths("s", _owned_proof(_ONE_COMPANY_EACH, 2))) == [
        ("s", "x", "t"), ("s", "y", "t"),
    ]


def test_the_same_fiber_joins_the_pair_when_nobody_owns_it() -> None:
    assert independent_paths("s", PathProofInputs(("s", "t"), build_adjacency(
        physical({("s", "x"): 1.0, ("x", "t"): 1.0, ("s", "y"): 1.0, ("y", "t"): 1.0}),
    ))) == [("s", "x", "t")]


_BOTH_HAVE_IT = fixtures.carrier_fiber_segments({("s", "t"): (1.0, ("lumen", "zayo"))})
_SHARE_A_CITY = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen", "zayo")),
    ("x", "t"): (1.0, ("lumen",)),
    ("x", "u"): (1.0, ("zayo",)),
    ("u", "t"): (1.0, ("zayo",)),
})


def test_a_way_out_both_carriers_have_is_drawn_once() -> None:
    assert independent_paths("s", _owned_proof(_BOTH_HAVE_IT)) == [("s", "t")]


def test_a_way_out_standing_on_a_city_already_spent_is_not_drawn() -> None:
    assert independent_paths("s", _owned_proof(_SHARE_A_CITY)) == [("s", "x", "t")]


def test_one_peer_takes_one_way_out_however_many_carriers_offer_one() -> None:
    assert independent_paths("s", _owned_proof(_ONE_COMPANY_EACH)) == [("s", "x", "t")]


_UNDER_WATER = fixtures.fiber_segments_under_water(
    {
        ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0,
        ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0,
    },
    {("sea", "tok"), ("tok", "hil")},
)
_UNDER_WATER_BACKBONE = ("hil", "sea")


def _on_land(
    fiber: dict[tuple[str, str], FiberSegment]
) -> dict[str, list[tuple[str, float]]]:
    return build_adjacency({
        segment: link for segment, link in fiber.items() if not link.submarine
    })


def test_a_way_round_under_water_is_no_way_out_where_the_site_has_one_over_land() -> None:
    assert independent_paths(
        "sea",
        PathProofInputs(
            _UNDER_WATER_BACKBONE,
            build_adjacency(_UNDER_WATER),
            paths_wanted=2,
            terrestrial=_on_land(_UNDER_WATER),
        ),
    ) == [("sea", "pdx", "hil")]


_ISLAND = fixtures.fiber_segments_under_water(
    {
        ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0,
        ("syd", "sea"): 8000.0, ("syd", "hil"): 8000.0,
    },
    {("syd", "sea"), ("syd", "hil")},
)
_ISLAND_BACKBONE = ("hil", "sea", "syd")


def test_a_site_reachable_only_over_water_keeps_the_ways_out_it_has() -> None:
    assert sorted(independent_paths(
        "syd",
        PathProofInputs(
            _ISLAND_BACKBONE,
            build_adjacency(_ISLAND),
            paths_wanted=2,
            terrestrial=_on_land(_ISLAND),
        ),
    )) == [("syd", "hil"), ("syd", "sea")]
