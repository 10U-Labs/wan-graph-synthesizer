from __future__ import annotations

import dataclasses
from pathlib import Path

from synthesizer.codec import OFF_NET_KIND, PROVIDER_KIND, SITE_KIND
from synthesizer.input_graph import FiberSegment, Site, SiteInfo, link_key
from synthesizer.model import (
    KIND_ROADM,
    Synthesis,
    SynthesisArtifacts,
    SynthesisInputs,
    SynthesisMetrics,
    SynthesisParams,
    ForcedLinks,
    OperatorLinks,
    SynthesisPath,
    RoleExclusions,
    SourceFiles,
    Tuning,
)
from synthesizer.graphs import (
    biconnected_block_membership,
    build_adjacency,
    path_link_keys,
)
from synthesizer.search_plan import _SearchPlan
from synthesizer.synthesize import all_pairs_shortest, synthesize_two_tier
from synthesizer.overrides import apply_role_overrides
from synthesizer.stages import dual_home, finalize
from synthesizer.validation import validate_synthesis

RING_COORDS = {
    "P0": (40.0, -100.0),
    "P1": (41.0, -100.0),
    "P2": (41.5, -99.0),
    "P3": (41.0, -98.0),
    "P4": (40.0, -98.0),
    "P5": (39.5, -99.0),
}
SPUR_COORDS = {"P6": (37.0, -100.0)}
RING_LINK_PAIRS = [
    ("P0", "P1"),
    ("P1", "P2"),
    ("P2", "P3"),
    ("P3", "P4"),
    ("P4", "P5"),
    ("P5", "P0"),
    ("P0", "P6"),
]
_FIXTURE_STATE = "XX"
_FIXTURE_COUNTRY = "United States"


def carrier_pop(site_id: str, lat: float = 0.0, lon: float = 0.0) -> Site:
    return Site(
        id=site_id,
        name=site_id,
        kind="PoP",
        coords=(lat, lon),
        info=SiteInfo(
            municipality=site_id, state=_FIXTURE_STATE, country=_FIXTURE_COUNTRY
        ),
    )


def access_site(site_id: str, lat: float = 0.0, lon: float = 0.0) -> Site:
    return Site(id=site_id, name=site_id, kind=SITE_KIND, coords=(lat, lon))


def provider_site(site_id: str, lat: float = 0.0, lon: float = 0.0) -> Site:
    return Site(id=site_id, name=site_id, kind=PROVIDER_KIND, coords=(lat, lon))


def off_net_site(site_id: str, lat: float = 0.0, lon: float = 0.0) -> Site:
    return Site(
        id=site_id,
        name=site_id,
        kind=OFF_NET_KIND,
        coords=(lat, lon),
        info=SiteInfo(
            municipality=site_id, state=_FIXTURE_STATE, country=_FIXTURE_COUNTRY
        ),
    )


def ring_sites() -> list[Site]:
    pops = [carrier_pop(n, lat, lon) for n, (lat, lon) in RING_COORDS.items()]
    pops += [carrier_pop(n, lat, lon) for n, (lat, lon) in SPUR_COORDS.items()]
    return pops


def ring_fiber_segments(distance: float = 100.0) -> dict[tuple[str, str], FiberSegment]:
    links: dict[tuple[str, str], FiberSegment] = {}
    for left, right in RING_LINK_PAIRS:
        key = link_key(left, right)
        links[key] = FiberSegment(source=key[0], target=key[1], distance_miles=distance)
    return links


SHARED_TRANSIT_BACKBONE = ("a", "b", "c")
SHARED_TRANSIT_PATHS = [("a", "x", "b"), ("a", "x", "c"), ("b", "c")]
DIVERSE_TRANSIT_PATHS = [("a", "x", "b"), ("a", "y", "c"), ("b", "c")]


def meshed_backbone_synthesis(
    paths: list[tuple[str, ...]], backbone_ids: tuple[str, ...]
) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys={key for path in paths for key in path_link_keys(path)},
        path_uses=[
            SynthesisPath("backbone_mesh", path[0], path[-1], path, 1.0) for path in paths
        ],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


SPLIT_BACKBONE = ("a", "b", "c", "d")
SPLIT_BACKBONE_CITIES = "abcdt"
SPLIT_BACKBONE_SEGMENTS = {("a", "t"): 50.0, ("t", "b"): 50.0, ("c", "d"): 100.0}


def split_backbone_synthesis() -> Synthesis:
    return Synthesis(
        backbone_ids=SPLIT_BACKBONE,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys={
            link_key(left, right) for left, right in SPLIT_BACKBONE_SEGMENTS
        },
        path_uses=[],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


def carrier_pops_in_a_column() -> list[Site]:
    return [
        carrier_pop("P0", 0.0, 0.0),
        carrier_pop("P1", 0.0, 1.0),
        carrier_pop("P2", 0.0, 2.0),
    ]


def carrier_pops_by_id(site_ids: str) -> dict[str, Site]:
    return {site_id: carrier_pop(site_id) for site_id in site_ids}


def fiber_segments_from(
    pairs: dict[tuple[str, str], float],
) -> dict[tuple[str, str], FiberSegment]:
    links: dict[tuple[str, str], FiberSegment] = {}
    for (left, right), dist in pairs.items():
        key = link_key(left, right)
        links[key] = FiberSegment(source=key[0], target=key[1], distance_miles=dist)
    return links


def carrier_fiber_segments(
    pairs: dict[tuple[str, str], tuple[float, tuple[str, ...]]],
) -> dict[tuple[str, str], FiberSegment]:
    links: dict[tuple[str, str], FiberSegment] = {}
    for (left, right), (dist, carriers) in pairs.items():
        key = link_key(left, right)
        links[key] = FiberSegment(
            source=key[0], target=key[1], distance_miles=dist,
            carriers=frozenset(carriers),
        )
    return links


def ring_params() -> SynthesisParams:
    return SynthesisParams(min_backbone_count=2)


def forced_off_net_case() -> tuple[Site, SynthesisParams]:
    site = off_net_site("Dulles Hub", 40.5, -100.0)
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=("Dulles Hub",),
    )
    return site, params


RingInputs = tuple[list[Site], dict[tuple[str, str], FiberSegment]]


def _ring_inputs() -> RingInputs:
    return ring_sites(), ring_fiber_segments()


def run_synthesis(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    params: SynthesisParams,
    off_net_sites: list[Site] | None = None,
) -> SynthesisArtifacts:
    sites, fiber_segments = dual_home(sites, fiber_segments, params, off_net_sites or [])
    sites, fiber_segments, overrides = apply_role_overrides(sites, fiber_segments, params)
    synthesis = synthesize_two_tier(sites, fiber_segments, params, overrides)
    sites, fiber_segments, synthesis, validation = finalize(
        sites, fiber_segments, synthesis, params, overrides.degree_exempt_backbone_ids
    )
    return SynthesisArtifacts(sites, fiber_segments, synthesis, validation)


def mesh_paths(artifacts: SynthesisArtifacts) -> list[SynthesisPath]:
    return [use for use in artifacts.synthesis.path_uses if use.purpose == "backbone_mesh"]


def synthesis_over_segments(
    site_ids: tuple[str, ...],
    segments: dict[tuple[str, str], float],
    number_of_diverse_paths: int,
    transit_ids: tuple[str, ...] = (),
    min_backbone_count: int | None = None,
) -> SynthesisArtifacts:
    return synthesis_over_fiber(
        site_ids, fiber_segments_from(segments), number_of_diverse_paths,
        transit_ids, min_backbone_count,
    )


def synthesis_over_owned_fiber(
    site_ids: tuple[str, ...],
    segments: dict[tuple[str, str], tuple[float, tuple[str, ...]]],
    number_of_diverse_paths: int,
    transit_ids: tuple[str, ...] = (),
) -> SynthesisArtifacts:
    return synthesis_over_fiber(
        site_ids, carrier_fiber_segments(segments), number_of_diverse_paths, transit_ids,
    )


def synthesis_over_fiber(
    site_ids: tuple[str, ...],
    fiber: dict[tuple[str, str], FiberSegment],
    number_of_diverse_paths: int,
    transit_ids: tuple[str, ...] = (),
    min_backbone_count: int | None = None,
) -> SynthesisArtifacts:
    cities = site_ids + transit_ids
    fewest = len(site_ids) if min_backbone_count is None else min_backbone_count
    return run_synthesis(
        [
            carrier_pop(city, 38.0, -115.0 + 2.0 * index)
            for index, city in enumerate(cities)
        ],
        fiber,
        SynthesisParams(
            min_backbone_count=fewest,
            max_backbone_count=len(site_ids),
            forced_backbone_names=site_ids,
            promote_high_degree_convergences=False,
            tuning=Tuning(backbone_number_of_diverse_paths=number_of_diverse_paths),
        ),
    )


def ring_artifacts() -> SynthesisArtifacts:
    sites, links = _ring_inputs()
    synthesis = synthesize_two_tier(sites, links, ring_params())
    return SynthesisArtifacts(sites, links, synthesis, validate_synthesis(sites, synthesis))


def ring_inputs_with_roadm(roadm_id: str) -> RingInputs:
    sites, links = _ring_inputs()
    sites = [
        dataclasses.replace(site, kind=KIND_ROADM) if site.id == roadm_id else site
        for site in sites
    ]
    return sites, links


def _forced_artifacts(
    params: SynthesisParams,
    inputs: RingInputs | None = None,
    links: OperatorLinks = OperatorLinks(),
) -> SynthesisArtifacts:
    sites, fiber_segments = inputs if inputs is not None else _ring_inputs()
    sites, fiber_segments, overrides = apply_role_overrides(
        sites, fiber_segments, params, links
    )
    synthesis = synthesize_two_tier(sites, fiber_segments, params, overrides)
    sites, fiber_segments, synthesis, validation = finalize(
        sites, fiber_segments, synthesis, params, overrides.degree_exempt_backbone_ids
    )
    return SynthesisArtifacts(sites, fiber_segments, synthesis, validation)


def forced_backbone_artifacts(name: str) -> SynthesisArtifacts:
    return _forced_artifacts(
        SynthesisParams(
            min_backbone_count=2,
            forced_backbone_names=(name,),
        )
    )


def forced_roadm_backbone_artifacts(name: str) -> SynthesisArtifacts:
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=(name,),
    )
    return _forced_artifacts(params, ring_inputs_with_roadm(name))


def prohibited_backbone_artifacts(name: str) -> SynthesisArtifacts:
    return _forced_artifacts(
        SynthesisParams(
            min_backbone_count=2,
            exclusions=RoleExclusions(prohibited_backbone_names=(name,)),
        )
    )


def ring_inputs_with_demand(access_id: str, at_pop: str) -> RingInputs:
    sites, links = _ring_inputs()
    return [*sites, access_site(access_id, *RING_COORDS[at_pop])], links


def forced_link_artifacts(
    params: SynthesisParams, links: OperatorLinks, inputs: RingInputs | None = None
) -> SynthesisArtifacts:
    return _forced_artifacts(params, inputs, links)


_HUB_CORNERS = ("hub_b0", "hub_b1", "hub_b2", "hub_b3")
_HUB_CENTER = "hub_dc"
_HUB_COORDS = {
    "hub_b0": (1.0, 0.0),
    "hub_b1": (0.0, 1.0),
    "hub_b2": (-1.0, 0.0),
    "hub_b3": (0.0, -1.0),
    "hub_dc": (0.0, 0.0),
}


def convergence_hub_inputs() -> RingInputs:
    pops = [carrier_pop(n, *_HUB_COORDS[n]) for n in (*_HUB_CORNERS, _HUB_CENTER)]
    spokes = {(_HUB_CENTER, corner): 1.0 for corner in _HUB_CORNERS}
    ring = {
        (_HUB_CORNERS[i], _HUB_CORNERS[(i + 1) % 4]): 1.5 for i in range(4)
    }
    return pops, fiber_segments_from({**spokes, **ring})


def convergence_hub_artifacts(
    max_backbone_count: int | None = None,
    promote_convergences: bool = True,
) -> SynthesisArtifacts:
    sites, links = convergence_hub_inputs()
    params = SynthesisParams(
        min_backbone_count=2,
        max_backbone_count=max_backbone_count,
        forced_backbone_names=_HUB_CORNERS,
        promote_high_degree_convergences=promote_convergences,
    )
    sites, links, overrides = apply_role_overrides(sites, links, params)
    synthesis = synthesize_two_tier(sites, links, params, overrides)
    return SynthesisArtifacts(sites, links, synthesis, validate_synthesis(sites, synthesis))


def sample_sources() -> SourceFiles:
    return SourceFiles((Path("sites/lumen.csv"),), Path("links.csv"))


def synthesis_inputs_from_links(
    link_ids: list[str],
    links: dict[tuple[str, str], FiberSegment],
    eligible: set[str],
    access_sites: list[Site] | None = None,
    coords: dict[str, tuple[float, float]] | None = None,
) -> SynthesisInputs:
    places = coords or {}
    pops = [carrier_pop(site_id, *places.get(site_id, (0.0, 0.0))) for site_id in link_ids]
    adjacency = build_adjacency(links)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return SynthesisInputs(
        access_sites=access_sites if access_sites is not None else [],
        carrier_pops=pops,
        fiber_segments=links,
        eligible_backbone_ids=eligible,
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
        carrier_blocks=biconnected_block_membership(adjacency),
    )


def search_plan(
    candidates: list[str],
    strength: dict[str, float] | None = None,
    access_backbone_links: int = 2,
    forced_links: ForcedLinks | None = None,
) -> _SearchPlan:
    strength_by_id = strength if strength is not None else {name: 1.0 for name in candidates}
    return _SearchPlan(
        candidates,
        strength_by_id,
        tuning=Tuning(access_backbone_links=access_backbone_links),
        forced_links=forced_links or ForcedLinks(),
    )


TRIANGLE = fiber_segments_from({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})


FUNNEL_LINKS = fiber_segments_from({
    ("funnel", "east_a"): 40.0,
    ("funnel", "east_b"): 45.0,
    ("funnel", "east_c"): 50.0,
    ("funnel", "east_d"): 55.0,
    ("funnel", "west_a"): 60.0,
    ("east_a", "choke_east"): 40.0,
    ("east_b", "choke_east"): 45.0,
    ("east_c", "choke_east"): 50.0,
    ("east_d", "choke_east"): 55.0,
    ("west_a", "choke_west"): 60.0,
    ("second_funnel", "east_e"): 40.0,
    ("second_funnel", "east_f"): 45.0,
    ("second_funnel", "east_g"): 50.0,
    ("second_funnel", "east_h"): 55.0,
    ("second_funnel", "west_b"): 60.0,
    ("east_e", "choke_east"): 40.0,
    ("east_f", "choke_east"): 45.0,
    ("east_g", "choke_east"): 50.0,
    ("east_h", "choke_east"): 55.0,
    ("west_b", "choke_west"): 60.0,
    ("choke_east", "north"): 70.0,
    ("choke_east", "south"): 70.0,
    ("choke_west", "west"): 70.0,
    ("spread", "north"): 80.0,
    ("spread", "south"): 80.0,
    ("spread", "west"): 80.0,
})
FUNNEL_IDS = [
    "funnel", "second_funnel", "spread", "north", "south", "west",
    "east_a", "east_b", "east_c", "east_d", "west_a",
    "east_e", "east_f", "east_g", "east_h", "west_b",
    "choke_east", "choke_west",
]
FUNNEL_ELIGIBLE = {"funnel", "second_funnel", "spread", "north", "south", "west"}
FUNNEL_COORDS = {
    "funnel": (40.0, -100.0),
    "east_a": (40.0, -99.0), "east_b": (40.05, -99.0),
    "east_c": (39.95, -99.0), "east_d": (40.0, -98.9),
    "west_a": (40.0, -101.0),
    "second_funnel": (36.0, -100.0),
    "east_e": (36.0, -99.0), "east_f": (36.05, -99.0),
    "east_g": (35.95, -99.0), "east_h": (36.0, -98.9),
    "west_b": (36.0, -101.0),
    "choke_east": (38.0, -98.0), "choke_west": (38.0, -102.0),
    "north": (42.0, -108.0), "south": (34.0, -108.0), "west": (38.0, -110.0),
    "spread": (38.0, -108.0),
}


def funnel_sites() -> list[Site]:
    return [carrier_pop(site_id, *FUNNEL_COORDS[site_id]) for site_id in FUNNEL_IDS]


def funnel_transit_names() -> tuple[str, ...]:
    return tuple(sorted(set(FUNNEL_COORDS) - FUNNEL_ELIGIBLE))


CROSSING_LINKS = fiber_segments_from({
    ("sea", "pdx"): 10.0,
    ("pdx", "hil"): 10.0,
    ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0,
    ("tok", "hil"): 1000.0,
    ("tok", "eug"): 1000.0,
})
CROSSING_IDS = ["sea", "hil", "eug", "pdx", "tok"]
CROSSING_ELIGIBLE = {"sea", "hil", "eug"}
CROSSING_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "eug": (44.0, -123.1),
    "tok": (35.7, 139.7),
}


def crossing_sites() -> list[Site]:
    return [carrier_pop(site_id, *CROSSING_COORDS[site_id]) for site_id in CROSSING_IDS]


def crossing_transit_names() -> tuple[str, ...]:
    return tuple(sorted(set(CROSSING_COORDS) - CROSSING_ELIGIBLE))


SHARED_HUB_SEGMENTS = {
    ("a", "h1"): 400.0, ("a", "h2"): 100.0, ("a", "h3"): 800.0,
    ("b", "h1"): 100.0, ("b", "h2"): 800.0, ("b", "h3"): 200.0,
    ("c", "h1"): 100.0, ("c", "h2"): 200.0, ("c", "h3"): 300.0,
}
SHARED_HUB_PEER_LINKS = fiber_segments_from({
    **SHARED_HUB_SEGMENTS,
    ("b", "d1"): 100.0, ("d1", "d"): 300.0,
    ("c", "d2"): 100.0, ("d2", "d"): 300.0,
})
SHARED_HUB_PEER_SITES = ("a", "b", "c", "d")
SHARED_HUB_PEER_IDS = ("a", "b", "c", "d", "h1", "h2", "h3", "d1", "d2")


def shared_hub_peer_sites() -> list[Site]:
    return [
        carrier_pop(site_id, 38.0, -115.0 + 2.0 * index)
        for index, site_id in enumerate(SHARED_HUB_PEER_IDS)
    ]


def shared_hub_peer_transit_names() -> tuple[str, ...]:
    return tuple(sorted(set(SHARED_HUB_PEER_IDS) - set(SHARED_HUB_PEER_SITES)))


def shared_hub_peer_artifacts(asked_for: int = 2) -> SynthesisArtifacts:
    return run_synthesis(
        shared_hub_peer_sites(),
        SHARED_HUB_PEER_LINKS,
        SynthesisParams(
            min_backbone_count=len(SHARED_HUB_PEER_SITES),
            max_backbone_count=len(SHARED_HUB_PEER_SITES),
            forced_backbone_names=SHARED_HUB_PEER_SITES,
            exclusions=RoleExclusions(
                prohibited_backbone_names=shared_hub_peer_transit_names()
            ),
            promote_high_degree_convergences=False,
            tuning=Tuning(backbone_number_of_diverse_paths=asked_for),
        ),
    )


DISTANT_PEER_LINKS = fiber_segments_from({
    ("sea", "pdx"): 10.0,
    ("pdx", "hil"): 10.0,
    ("sea", "tok"): 1000.0,
    ("tok", "hil"): 1000.0,
    ("pdx", "syd"): 7000.0,
    ("hil", "syd"): 7000.0,
})
DISTANT_PEER_IDS = ["sea", "hil", "syd", "pdx", "tok"]
DISTANT_PEER_ELIGIBLE = {"sea", "hil", "syd"}
DISTANT_PEER_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "syd": (-33.9, 151.2),
    "tok": (35.7, 139.7),
}


def distant_peer_sites() -> list[Site]:
    return [
        carrier_pop(site_id, *DISTANT_PEER_COORDS[site_id])
        for site_id in DISTANT_PEER_IDS
    ]


def distant_peer_transit_names() -> tuple[str, ...]:
    return tuple(sorted(set(DISTANT_PEER_COORDS) - DISTANT_PEER_ELIGIBLE))


EXPRESS_LINKS = fiber_segments_from({
    ("sea", "pdx"): 1.0,
    ("pdx", "hil"): 1.0,
    ("hil", "alb"): 1.0,
    ("alb", "eug"): 1.0,
    ("eug", "tac"): 1.0,
    ("tac", "sea"): 1.0,
    ("sea", "hil"): 5.0,
    ("hil", "eug"): 5.0,
    ("eug", "sea"): 5.0,
})
EXPRESS_IDS = ["sea", "hil", "eug", "pdx", "alb", "tac"]
EXPRESS_ELIGIBLE = {"sea", "hil", "eug"}
EXPRESS_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "alb": (44.6, -123.1),
    "eug": (44.0, -123.1),
    "tac": (46.0, -122.9),
}


def express_sites() -> list[Site]:
    return [carrier_pop(site_id, *EXPRESS_COORDS[site_id]) for site_id in EXPRESS_IDS]


def express_transit_names() -> tuple[str, ...]:
    return tuple(sorted(set(EXPRESS_COORDS) - EXPRESS_ELIGIBLE))


def funnel_inputs() -> SynthesisInputs:
    return synthesis_inputs_from_links(
        FUNNEL_IDS, FUNNEL_LINKS, set(FUNNEL_ELIGIBLE), coords=FUNNEL_COORDS
    )


TWO_POCKET_LINKS = fiber_segments_from(
    {
        ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0, ("c", "d"): 1.0,
        ("d", "e"): 1.0, ("e", "f"): 1.0, ("d", "f"): 1.0,
    }
)
TWO_POCKET_IDS = ["a", "b", "c", "d", "e", "f"]


MANY_PASS_SEGMENTS = {
    ("a", "c"): 32.0, ("a", "e"): 22.0, ("a", "f"): 18.0, ("a", "g"): 25.0,
    ("b", "c"): 36.0, ("b", "h"): 30.0, ("b", "i"): 22.0,
    ("c", "e"): 22.0, ("c", "h"): 7.0, ("c", "i"): 25.0, ("c", "j"): 28.0,
    ("d", "f"): 36.0, ("d", "j"): 22.0, ("d", "k"): 7.0, ("d", "l"): 11.0,
    ("e", "f"): 39.0, ("e", "g"): 25.0, ("e", "h"): 21.0, ("e", "i"): 25.0,
    ("f", "j"): 25.0, ("f", "k"): 34.0,
    ("h", "i"): 18.0, ("h", "j"): 35.0,
    ("j", "k"): 16.0, ("j", "l"): 32.0,
    ("k", "l"): 18.0,
}
MANY_PASS_SITES = ("c", "d", "j", "k", "l")
MANY_PASS_TRANSIT = ("a", "b", "e", "f", "g", "h", "i")
MANY_PASS_MILES = 159.0


SELLABLE_WAYS_SITES = ("a", "b")
SELLABLE_WAYS_TRANSIT = ("p", "q", "r")
SELLABLE_WAYS_SEGMENTS: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {
    ("a", "p"): (1.0, ("zayo",)),
    ("b", "p"): (1.0, ("lumen",)),
    ("a", "q"): (1.0, ("zayo",)),
    ("b", "q"): (1.0, ("lumen",)),
    ("a", "r"): (2.5, ("lumen",)),
    ("b", "r"): (2.5, ("lumen",)),
}
SELLABLE_WAYS_LINKS = carrier_fiber_segments(SELLABLE_WAYS_SEGMENTS)

NEAR_AND_FAR_SITES = ("a", "b", "far")
NEAR_AND_FAR_LINKS = fiber_segments_from({
    ("a", "b"): 1.0,
    ("a", "q"): 2.0, ("b", "q"): 2.0,
    ("a", "far"): 100.0, ("b", "far"): 100.0,
})
