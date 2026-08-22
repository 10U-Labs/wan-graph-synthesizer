from __future__ import annotations

from synthesizer.ceiling import PathProofInputs, diverse_path_ceilings
from synthesizer.graphs import adjacency_by_carrier, build_adjacency
from synthesizer.input_graph import FiberSegment, Site
from synthesizer.model import Synthesis, SynthesisParams, MeshRequirements, ValidationReport
from synthesizer.on_net_fabrication import fabricate_missing_on_net_nodes
from synthesizer.offnet import realize_off_net_sites
from synthesizer.validation import (
    backbone_names_by_group,
    node_mesh_target,
    validate_synthesis,
)


def dual_home(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    params: SynthesisParams,
    off_net_sites: list[Site],
) -> tuple[list[Site], dict[tuple[str, str], FiberSegment]]:
    forced_backbone = frozenset(params.forced_backbone_names)
    fabricated = fabricate_missing_on_net_nodes(
        sites, fiber_segments, forced_backbone
    )
    sites, fiber_segments = fabricated.sites, fabricated.fiber_segments
    off_net = realize_off_net_sites(
        sites,
        fiber_segments,
        off_net_sites,
        forced_backbone,
    )
    return off_net.sites, off_net.fiber_segments


def finalize(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    synthesis: Synthesis,
    params: SynthesisParams,
    degree_exempt: frozenset[str] = frozenset(),
) -> tuple[
    list[Site], dict[tuple[str, str], FiberSegment], Synthesis, ValidationReport
]:
    adjacency = build_adjacency(fiber_segments)
    terrestrial = build_adjacency({
        segment: link for segment, link in fiber_segments.items() if not link.submarine
    })
    targets = MeshRequirements(
        number_of_diverse_paths=params.tuning.backbone_number_of_diverse_paths,
        degree_exempt=degree_exempt,
        ceilings=diverse_path_ceilings(PathProofInputs(
            synthesis.backbone_ids,
            adjacency,
            None,
            params.tuning.backbone_number_of_diverse_paths,
            params.max_backbone_count,
            adjacency_by_carrier(fiber_segments),
            terrestrial,
        )),
    )
    validation = validate_synthesis(
        sites, synthesis, params.tuning.access_backbone_links, targets
    )
    if not validation["connected"]:
        groups = "; ".join(
            ", ".join(names) for names in backbone_names_by_group(sites, synthesis)
        )
        raise ValueError(
            f"Synthesis falls into {validation['component_count']} groups "
            f"no fiber joins: {groups}"
        )
    deficient = validation["backbone_mesh_independence_deficient"]
    if deficient:
        shortfalls = ", ".join(
            f"{entry['name']} ({entry['independent_degree']} of "
            f"{node_mesh_target(str(entry['id']), targets)})"
            for entry in deficient
        )
        raise ValueError(
            f"Too few independently failing backbone mesh links at: {shortfalls}"
        )
    return sites, fiber_segments, synthesis, validation
