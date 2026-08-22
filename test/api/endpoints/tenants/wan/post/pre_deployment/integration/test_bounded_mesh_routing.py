from __future__ import annotations

import fixtures
from synthesizer.input_graph import FiberSegment, Site
from synthesizer.model import (
    RoleExclusions,
    SynthesisArtifacts,
    SynthesisParams,
    Tuning,
)

_SEATS = 3


def _artifacts(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    transit_names: tuple[str, ...],
    multiple: float,
) -> SynthesisArtifacts:
    return fixtures.run_synthesis(
        sites,
        fiber_segments,
        SynthesisParams(
            min_backbone_count=_SEATS,
            max_backbone_count=_SEATS,
            exclusions=RoleExclusions(prohibited_backbone_names=transit_names),
            promote_high_degree_convergences=False,
            tuning=Tuning(
                backbone_number_of_diverse_paths=2, backbone_max_backup_path_multiple=multiple
            ),
        ),
    )


def _crossing(multiple: float) -> SynthesisArtifacts:
    return _artifacts(
        fixtures.crossing_sites(),
        fixtures.CROSSING_LINKS,
        fixtures.crossing_transit_names(),
        multiple,
    )


BOUNDED = _crossing(3.0)
UNBOUNDED = _crossing(1000.0)
DISTANT_PEER = _artifacts(
    fixtures.distant_peer_sites(),
    fixtures.DISTANT_PEER_LINKS,
    fixtures.distant_peer_transit_names(),
    3.0,
)
EXPRESS = _artifacts(
    fixtures.express_sites(),
    fixtures.EXPRESS_LINKS,
    fixtures.express_transit_names(),
    3.0,
)


def _cities_crossed(artifacts: SynthesisArtifacts) -> set[str]:
    return {
        city
        for use in artifacts.synthesis.path_uses
        if use.purpose == "backbone_mesh"
        for city in use.path
    }


def _mesh_miles(artifacts: SynthesisArtifacts) -> float:
    return sum(
        use.distance_miles for use in artifacts.synthesis.path_uses
        if use.purpose == "backbone_mesh"
    )


def test_the_bounded_synthesis_paths_no_link_through_the_crossing() -> None:
    assert "tok" not in _cities_crossed(BOUNDED)


def test_a_bound_wide_enough_still_takes_the_crossing() -> None:
    assert "tok" in _cities_crossed(UNBOUNDED)


def test_the_bounded_synthesis_still_wires_every_site_into_one_backbone() -> None:
    assert BOUNDED.validation["connected"]


def test_the_bounded_ceiling_is_the_honest_one() -> None:
    limited = {
        str(entry["id"]): entry["ceiling"]
        for entry in BOUNDED.validation["backbone_diverse_paths_ceiling_limited"]
    }
    assert limited == {"eug": 1, "hil": 1, "sea": 1}


def test_the_unbounded_ceiling_counts_the_crossing() -> None:
    assert UNBOUNDED.validation["backbone_diverse_paths_ceiling_limited"] == []


def test_no_site_is_asked_for_a_link_the_bound_will_not_let_the_mesh_lay() -> None:
    assert DISTANT_PEER.validation["backbone_mesh_independence_deficient"] == []


def test_the_distant_peer_ceiling_is_the_one_its_usable_fiber_carries() -> None:
    limited = {
        str(entry["id"]): entry["ceiling"]
        for entry in DISTANT_PEER.validation["backbone_diverse_paths_ceiling_limited"]
    }
    assert limited == {"sea": 1}


def test_the_finished_synthesis_orders_the_fewest_fiber_miles_it_can_be_wired_with() -> None:
    assert _mesh_miles(EXPRESS) == 6.0


def test_the_ring_synthesis_holds_every_site_to_the_two_links_its_fiber_carries() -> None:
    assert EXPRESS.validation["backbone_mesh_independence_deficient"] == []
