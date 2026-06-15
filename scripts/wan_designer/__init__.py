"""Three-tier WAN graph designer package.

Re-exports the public API used by the CLI entry point and the test suite.
"""

from __future__ import annotations

from wan_designer.model import (
    AccessEdge,
    CliPaths,
    Design,
    DesignArtifacts,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    Vertex,
    PathUse,
    PhysicalEdge,
    SourceFiles,
    Tuning,
    ValidationReport,
    carrier_role,
    edge_key,
    haversine_miles,
    is_carrier_pop,
    slugify,
)
from wan_designer.parsing import (
    build_adjacency,
    load_carrier_edges,
    load_vertices,
)
from wan_designer.graphs import (
    articulation_points,
    connected_components,
    dijkstra,
    vertex_disjoint_paths_to_cores,
    reconstruct_path,
)
from wan_designer.validation import (
    aggregations_without_core_redundancy,
    augment_physical_resilience,
    disconnected_core_pairs,
    validate_design,
)
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.config import AppConfig, load_config
from wan_designer.cli import main

__all__ = [
    "AccessEdge",
    "AppConfig",
    "CliPaths",
    "Design",
    "DesignArtifacts",
    "DesignInputs",
    "DesignMetrics",
    "DesignParams",
    "Vertex",
    "PathUse",
    "PhysicalEdge",
    "SourceFiles",
    "Tuning",
    "ValidationReport",
    "aggregations_without_core_redundancy",
    "articulation_points",
    "augment_physical_resilience",
    "build_adjacency",
    "carrier_role",
    "connected_components",
    "dijkstra",
    "disconnected_core_pairs",
    "edge_key",
    "haversine_miles",
    "is_carrier_pop",
    "load_carrier_edges",
    "load_config",
    "load_vertices",
    "main",
    "vertex_disjoint_paths_to_cores",
    "optimize_three_tier_design",
    "reconstruct_path",
    "slugify",
    "validate_design",
]
