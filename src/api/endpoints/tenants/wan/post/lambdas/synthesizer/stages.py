"""The WAN synthesis pipeline as composable steps.

The synthesizer composes these over the JSON-loaded graph:
``dual_home`` -> ``apply_role_overrides`` -> ``synthesize_two_tier`` ->
``finalize``.
"""

from __future__ import annotations

from synthesizer.ceiling import BackupPathLimit, PathProofInputs, diverse_path_ceilings
from synthesizer.graphs import build_adjacency, distances_from
from synthesizer.input_graph import PhysicalEdge, Vertex
from synthesizer.model import Synthesis, SynthesisParams, MeshRequirements, ValidationReport
from synthesizer.on_net_fabrication import fabricate_missing_on_net_nodes
from synthesizer.offnet import realize_off_net_sites
from synthesizer.validation import (
    backbone_names_by_group,
    node_mesh_target,
    validate_synthesis,
)


def dual_home(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: SynthesisParams,
    off_net_sites: list[Vertex],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Attach demand to the carrier graph: fabricate on-net nodes, then off-net seats.

    ``off_net_sites`` are the loaded off-net candidate vertices (the caller loads
    them, from a CSV file or the stored JSON), so this step is source-agnostic. Both
    fabrication paths are gated by ``params.datacenter_cities``: a forced location off a
    data-center city is rejected, since the backbone gate is absolute. When
    ``params.datacenter_cities`` is ``None`` (free-for-all) a forced location at any city
    is fabricated.
    """
    forced_backbone = frozenset(params.forced_backbone_names)
    fabricated = fabricate_missing_on_net_nodes(
        vertices, physical_edges, forced_backbone, params.datacenter_cities
    )
    vertices, physical_edges = fabricated.vertices, fabricated.physical_edges
    off_net = realize_off_net_sites(
        vertices,
        physical_edges,
        off_net_sites,
        forced_backbone,
        params.datacenter_cities,
    )
    return off_net.vertices, off_net.physical_edges


def finalize(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    synthesis: Synthesis,
    params: SynthesisParams,
    degree_exempt: frozenset[str] = frozenset(),
) -> tuple[
    list[Vertex], dict[tuple[str, str], PhysicalEdge], Synthesis, ValidationReport
]:
    """Validate the synthesis over the real fiber, refusing one no operator could build from.

    Two things are refused here, and a refusal means the build is recorded as ``fail`` and
    nothing is published. The first is a synthesis in more than one group: a network whose
    sites cannot all reach one another is not one network, and an operator handed it can
    carry no traffic between the groups. Every site can still hold every link it was asked
    for while that is true -- a site meets its count against peers inside its own group --
    so the diverse path count below does not see the split and cannot (GitHub issue #68).

    The second is a synthesis that misses its diverse path count. Resilience is the operator's
    two required redundancy degrees, enforced over the real fiber and reported by
    :func:`validate_synthesis`; there is no silent edge augmentation.

    ``backbone_number_of_diverse_paths`` is a count of links that fail independently, so a synthesis
    where some backbone node cannot reach its target is not a synthesis that meets the
    configuration and is refused by name.

    What each node's target is, though, is not the configured degree flat. The ceilings are
    computed here from the fiber this stage is already handed (see
    :mod:`synthesizer.ceiling`), and a node is asked for the smaller of the degree and what
    its own fiber can independently carry. So a refusal now means a shortfall the ground
    does not explain -- the routing left a node under what its fiber supports, which is a
    defect somebody can fix -- rather than an operator pinning a city whose fiber was never
    going to make the number. The message names both counts for that reason.

    ``degree_exempt`` are the backbone nodes the operator has held to no degree, already
    resolved to ids. Their shortfall is neither reported nor refused: saying in advance
    that a node is a spur is the third answer -- alongside pinning elsewhere and
    lowering the degree -- and the only one that leaves the rest of the backbone at the
    degree it was configured with. It silences the check and nothing else; the node still
    took every link its fiber could carry.
    """
    adjacency = build_adjacency(physical_edges)
    targets = MeshRequirements(
        number_of_diverse_paths=params.tuning.backbone_number_of_diverse_paths,
        degree_exempt=degree_exempt,
        ceilings=diverse_path_ceilings(PathProofInputs(
            synthesis.backbone_ids,
            adjacency,
            BackupPathLimit(
                params.tuning.backbone_max_backup_path_multiple,
                distances_from(adjacency, synthesis.backbone_ids),
            ),
            params.tuning.backbone_number_of_diverse_paths,
            params.max_backbone_count,
        )),
    )
    validation = validate_synthesis(
        vertices, synthesis, params.tuning.access_backbone_links, targets
    )
    if not validation["connected"]:
        groups = "; ".join(
            ", ".join(names) for names in backbone_names_by_group(vertices, synthesis)
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
    return vertices, physical_edges, synthesis, validation
