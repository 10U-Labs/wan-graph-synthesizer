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
    Node,
    PathUse,
    PhysicalEdge,
    SourceFiles,
    ValidationReport,
    classify_category,
    edge_key,
    haversine_miles,
    slugify,
)
from wan_designer.parsing import (
    build_adjacency,
    load_carrier_edges,
    load_nodes,
    load_pop_roles,
    load_regional_networks,
    load_regional_nodes,
)
from wan_designer.graphs import (
    articulation_points,
    connected_components,
    dijkstra,
    node_disjoint_paths_to_cores,
    reconstruct_path,
)
from wan_designer.validation import (
    aggregations_without_core_redundancy,
    augment_physical_resilience,
    disconnected_core_pairs,
    validate_design,
)
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.cli import main

__all__ = [
    "AccessEdge",
    "CliPaths",
    "Design",
    "DesignArtifacts",
    "DesignInputs",
    "DesignMetrics",
    "DesignParams",
    "Node",
    "PathUse",
    "PhysicalEdge",
    "SourceFiles",
    "ValidationReport",
    "aggregations_without_core_redundancy",
    "articulation_points",
    "augment_physical_resilience",
    "build_adjacency",
    "classify_category",
    "connected_components",
    "dijkstra",
    "disconnected_core_pairs",
    "edge_key",
    "haversine_miles",
    "load_carrier_edges",
    "load_nodes",
    "load_pop_roles",
    "load_regional_networks",
    "load_regional_nodes",
    "main",
    "node_disjoint_paths_to_cores",
    "optimize_three_tier_design",
    "reconstruct_path",
    "slugify",
    "validate_design",
]
