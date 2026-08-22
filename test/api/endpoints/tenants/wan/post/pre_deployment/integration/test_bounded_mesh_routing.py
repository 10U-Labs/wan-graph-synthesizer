from __future__ import annotations

import pytest

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


@pytest.fixture(name="bounded", scope="module")
def _bounded() -> SynthesisArtifacts:
    return _crossing(3.0)


@pytest.fixture(name="unbounded", scope="module")
def _unbounded() -> SynthesisArtifacts:
    return _crossing(1000.0)


@pytest.fixture(name="distant_peer", scope="module")
def _distant_peer() -> SynthesisArtifacts:
    return _artifacts(
        fixtures.distant_peer_sites(),
        fixtures.DISTANT_PEER_LINKS,
        fixtures.distant_peer_transit_names(),
        3.0,
    )


@pytest.fixture(name="express", scope="module")
def _express() -> SynthesisArtifacts:
    return _artifacts(
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


def _limited_ceilings(artifacts: SynthesisArtifacts) -> dict[str, int]:
    return {
        str(entry["id"]): entry["ceiling"]
        for entry in artifacts.validation["backbone_diverse_paths_ceiling_limited"]
    }


def test_the_bounded_synthesis_paths_no_link_through_the_crossing(
    bounded: SynthesisArtifacts,
) -> None:
    assert "tok" not in _cities_crossed(bounded)


def test_a_bound_wide_enough_still_takes_the_crossing(
    unbounded: SynthesisArtifacts,
) -> None:
    assert "tok" in _cities_crossed(unbounded)


def test_the_bounded_synthesis_still_wires_every_site_into_one_backbone(
    bounded: SynthesisArtifacts,
) -> None:
    assert bounded.validation["connected"]


def test_the_bounded_ceiling_is_the_honest_one(bounded: SynthesisArtifacts) -> None:
    assert _limited_ceilings(bounded) == {"eug": 1, "hil": 1, "sea": 1}


def test_the_unbounded_ceiling_counts_the_crossing(
    unbounded: SynthesisArtifacts,
) -> None:
    assert unbounded.validation["backbone_diverse_paths_ceiling_limited"] == []


def test_no_site_is_asked_for_a_link_the_bound_will_not_let_the_mesh_lay(
    distant_peer: SynthesisArtifacts,
) -> None:
    assert distant_peer.validation["backbone_mesh_independence_deficient"] == []


def test_the_distant_peer_ceiling_is_the_one_its_usable_fiber_carries(
    distant_peer: SynthesisArtifacts,
) -> None:
    assert _limited_ceilings(distant_peer) == {"sea": 1}


def test_the_finished_synthesis_orders_the_fewest_fiber_miles_it_can_be_wired_with(
    express: SynthesisArtifacts,
) -> None:
    assert _mesh_miles(express) == 6.0


def test_the_ring_synthesis_holds_every_site_to_the_two_links_its_fiber_carries(
    express: SynthesisArtifacts,
) -> None:
    assert express.validation["backbone_mesh_independence_deficient"] == []
