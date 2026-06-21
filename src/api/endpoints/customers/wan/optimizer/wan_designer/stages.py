"""The WAN design pipeline as composable steps.

The optimizer entrypoint composes these over the JSON-loaded graph:
``dual_home`` -> ``apply_role_overrides`` -> ``optimize_three_tier_design`` ->
``finalize``.
"""

from __future__ import annotations

from wan_graph.model import (
    Design,
    DesignParams,
    PhysicalEdge,
    ValidationReport,
    Vertex,
)
from wan_designer.installations import realize_installations
from wan_designer.offnet import realize_off_net_sites
from wan_designer.overrides import materialize_selected_colocation_twins
from wan_designer.validation import augment_physical_resilience, validate_design


def dual_home(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    off_net_sites: list[Vertex],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Attach demand to the carrier graph: realize installations, then off-net seats.

    ``off_net_sites`` are the loaded off-net candidate vertices (the caller loads
    them, from a CSV file or the stored JSON), so this step is source-agnostic.
    """
    realized = realize_installations(
        vertices, physical_edges, frozenset(params.forced_aggregation_names)
    )
    vertices, physical_edges = realized.vertices, realized.physical_edges
    off_net = realize_off_net_sites(
        vertices,
        physical_edges,
        off_net_sites,
        frozenset(params.forced_core_names) | frozenset(params.forced_aggregation_names),
    )
    return off_net.vertices, off_net.physical_edges


def finalize(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    design: Design,
    params: DesignParams,
    augment: bool,
) -> tuple[
    list[Vertex], dict[tuple[str, str], PhysicalEdge], Design, ValidationReport
]:
    """Materialize selected co-location twins, optionally augment, then validate."""
    vertices, physical_edges = materialize_selected_colocation_twins(
        vertices, physical_edges, design
    )
    if augment:
        design = augment_physical_resilience(vertices, physical_edges, design)
    validation = validate_design(
        vertices,
        design,
        params.tuning.access_aggregation_links,
        params.tuning.core_links_per_core,
    )
    return vertices, physical_edges, design, validation
