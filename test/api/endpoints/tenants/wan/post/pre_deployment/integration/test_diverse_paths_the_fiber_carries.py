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
) -> SynthesisArtifacts:
    return fixtures.run_synthesis(
        sites,
        fiber_segments,
        SynthesisParams(
            min_backbone_count=_SEATS,
            max_backbone_count=_SEATS,
            exclusions=RoleExclusions(prohibited_backbone_names=transit_names),
            promote_high_degree_convergences=False,
            tuning=Tuning(backbone_number_of_diverse_paths=2),
        ),
    )


@pytest.fixture(name="crossing", scope="module")
def _crossing() -> SynthesisArtifacts:
    return _artifacts(
        fixtures.crossing_sites(),
        fixtures.CROSSING_LINKS,
        fixtures.crossing_transit_names(),
    )


@pytest.fixture(name="under_water", scope="module")
def _under_water() -> SynthesisArtifacts:
    return _artifacts(
        fixtures.crossing_sites(),
        fixtures.CROSSING_SUBMARINE_LINKS,
        fixtures.crossing_transit_names(),
    )


@pytest.fixture(name="distant_peer", scope="module")
def _distant_peer() -> SynthesisArtifacts:
    return _artifacts(
        fixtures.distant_peer_sites(),
        fixtures.DISTANT_PEER_LINKS,
        fixtures.distant_peer_transit_names(),
    )


@pytest.fixture(name="express", scope="module")
def _express() -> SynthesisArtifacts:
    return _artifacts(
        fixtures.express_sites(),
        fixtures.EXPRESS_LINKS,
        fixtures.express_transit_names(),
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


def test_a_crossing_is_taken_where_it_is_a_site_second_way_out(
    crossing: SynthesisArtifacts,
) -> None:
    assert "tok" in _cities_crossed(crossing)


def test_a_crossing_a_way_round_over_land_answers_is_not_taken(
    under_water: SynthesisArtifacts,
) -> None:
    assert "tok" not in _cities_crossed(under_water)


def test_the_synthesis_wires_every_site_into_one_backbone(
    crossing: SynthesisArtifacts,
) -> None:
    assert crossing.validation["connected"]


def test_no_site_is_credited_with_a_way_out_its_fiber_does_not_carry(
    crossing: SynthesisArtifacts,
) -> None:
    assert crossing.validation["backbone_diverse_paths_ceiling_limited"] == []


def test_no_site_is_asked_for_a_link_its_fiber_cannot_lay(
    distant_peer: SynthesisArtifacts,
) -> None:
    assert distant_peer.validation["backbone_mesh_independence_deficient"] == []


def test_the_finished_synthesis_orders_the_fewest_fiber_miles_it_can_be_wired_with(
    express: SynthesisArtifacts,
) -> None:
    assert _mesh_miles(express) == 6.0


def test_the_ring_synthesis_holds_every_site_to_the_two_links_its_fiber_carries(
    express: SynthesisArtifacts,
) -> None:
    assert express.validation["backbone_mesh_independence_deficient"] == []
