"""The WAN design pipeline as composable steps.

``run_design`` (service.py) and the per-customer WAN create compose these steps:
``load_inputs`` -> ``dual_home`` -> ``apply_role_overrides`` -> ``optimize_three_tier_design``
-> ``finalize``. ``combine_substrate`` yields the shared carrier mesh on its own.
"""

from __future__ import annotations

from wan_designer.installations import realize_installations
from wan_designer.model import (
    Design,
    DesignParams,
    DesignPaths,
    PhysicalEdge,
    ValidationReport,
    Vertex,
    is_carrier_pop,
)
from wan_designer.offnet import realize_off_net_sites
from wan_designer.overrides import materialize_selected_colocation_twins
from wan_designer.parsing import load_carrier_edges, load_vertices
from wan_designer.validation import augment_physical_resilience, validate_design


def load_inputs(
    paths: DesignPaths,
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Load every vertex and the carrier fiber edges from the configured files."""
    vertices = load_vertices(list(paths.vertex_files))
    if not vertices:
        raise ValueError("No vertices found in the configured vertex files")
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    physical_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in (paths.edge_path, *paths.regional_edge_paths):
        physical_edges.update(load_carrier_edges(edge_path, carrier_pops))
    return vertices, physical_edges


def combine_substrate(
    paths: DesignPaths,
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """The shared substrate: every carrier PoP stitched over the carrier fiber.

    Non-carrier vertices (CSP regions, installations) are dropped -- the substrate is
    the carriers' shared physical mesh; demand is homed onto it per customer.
    """
    vertices, physical_edges = load_inputs(paths)
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    return carrier_pops, physical_edges


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
