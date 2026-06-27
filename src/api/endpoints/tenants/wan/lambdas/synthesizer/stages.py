"""The WAN design pipeline as composable steps.

The synthesizer worker composes these over the JSON-loaded graph:
``dual_home`` -> ``apply_role_overrides`` -> ``synthesize_two_tier_design`` ->
``finalize``.
"""

from __future__ import annotations

from synthesizer.input_graph import PhysicalEdge, Vertex
from synthesizer.model import Design, DesignParams, ValidationReport
from synthesizer.on_net_fabrication import fabricate_missing_on_net_nodes
from synthesizer.offnet import realize_off_net_sites
from synthesizer.validation import validate_design


def dual_home(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    off_net_sites: list[Vertex],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Attach demand to the carrier graph: fabricate on-net nodes, then off-net seats.

    ``off_net_sites`` are the loaded off-net candidate vertices (the caller loads
    them, from a CSV file or the stored JSON), so this step is source-agnostic. Both
    fabrication paths are gated by ``params.datacenter_cities``: a forced location off
    a data-center city is rejected, since the backbone gate is absolute.
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
    design: Design,
    params: DesignParams,
) -> tuple[
    list[Vertex], dict[tuple[str, str], PhysicalEdge], Design, ValidationReport
]:
    """Validate the design over the real fiber.

    Resilience is the operator's two required redundancy degrees, enforced over the
    real fiber and reported by :func:`validate_design`; there is no silent edge
    augmentation.
    """
    validation = validate_design(
        vertices,
        design,
        params.tuning.access_backbone_links,
        params.tuning.backbone_mesh_degree,
    )
    return vertices, physical_edges, design, validation
