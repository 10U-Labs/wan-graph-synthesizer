"""Command-line interface for the three-tier WAN designer."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from wan_designer.model import (
    CliPaths,
    DesignArtifacts,
    DesignParams,
    SourceFiles,
    ValidationReport,
)
from wan_designer.parsing import load_carrier_edges, load_nodes, load_pop_roles
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.validation import (
    augment_physical_resilience,
    included_node_ids,
    validate_design,
)
from wan_designer.output import write_outputs


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute a three-tier core/aggregation/access WAN over the "
            "Carrier mapbook edge graph."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="f35_sentinel_secret_regions_carrier_400g.kmz",
        help="Input KMZ or KML file. Defaults to the project KMZ.",
    )
    parser.add_argument(
        "--carrier-edges",
        default="data/carrier_edges.csv",
        help="CSV of physical Carrier mapbook route edges.",
    )
    parser.add_argument(
        "--pop-roles",
        default="data/carrier_pop_roles.csv",
        help="Optional CSV of Carrier PoP roles from the mapbook legend.",
    )
    parser.add_argument(
        "--mapbook-pdf",
        default="",
        help="Optional source PDF path recorded in JSON output.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for JSON, CSV, KML, and DOT outputs.",
    )
    parser.add_argument(
        "--core-count",
        type=int,
        default=3,
        help="Minimum number of core nodes; more are added if needed. Default is 3.",
    )
    parser.add_argument(
        "--core-candidate-limit",
        type=int,
        default=32,
        help="Number of strongest Carrier PoPs to consider as cores.",
    )
    parser.add_argument(
        "--aggregation-candidates-per-access",
        type=int,
        default=8,
        help="Nearest eligible aggregation PoPs considered per access node.",
    )
    parser.add_argument(
        "--aggregation-penalty-miles",
        type=float,
        default=40.0,
        help="Facility penalty used to avoid selecting unnecessary aggregation PoPs.",
    )
    parser.add_argument(
        "--allow-roadm-aggregation",
        action="store_true",
        help="Allow mapbook ROADM nodes to be selected as aggregation/core points.",
    )
    parser.add_argument(
        "--no-resilience-augmentation",
        action="store_true",
        help="Do not add extra physical Carrier edges to reduce articulation or degree risk.",
    )
    return parser

def cli_paths(args: argparse.Namespace) -> CliPaths:
    """Resolve command-line arguments into concrete file paths."""
    return CliPaths(
        input_path=Path(args.input),
        edge_path=Path(args.carrier_edges),
        role_path=Path(args.pop_roles) if args.pop_roles else None,
        mapbook_pdf=Path(args.mapbook_pdf) if args.mapbook_pdf else None,
        output_dir=Path(args.output_dir),
    )

def params_from_args(args: argparse.Namespace) -> DesignParams:
    """Build the design parameter bundle from parsed CLI arguments."""
    return DesignParams(
        core_count=args.core_count,
        core_candidate_limit=args.core_candidate_limit,
        aggregation_candidates_per_access=args.aggregation_candidates_per_access,
        aggregation_penalty_miles=args.aggregation_penalty_miles,
        allow_roadm_aggregation=args.allow_roadm_aggregation,
    )

def run_design(paths: CliPaths, params: DesignParams, augment: bool) -> DesignArtifacts:
    """Load inputs, optimize the design, and validate it."""
    nodes = load_nodes(paths.input_path)
    if not nodes:
        raise ValueError(f"No point placemarks found in {paths.input_path}")
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    physical_edges = load_carrier_edges(paths.edge_path, carrier_pops)
    roles = load_pop_roles(paths.role_path, carrier_pops)
    design = optimize_three_tier_design(nodes, physical_edges, roles, params)
    if augment:
        design = augment_physical_resilience(nodes, physical_edges, design)
    validation = validate_design(nodes, design)
    return DesignArtifacts(nodes, physical_edges, design, validation)

def print_summary(
    paths: CliPaths, artifacts: DesignArtifacts, outputs: dict[str, Path]
) -> None:
    """Print a human-readable summary of the computed design."""
    design = artifacts.design
    validation = artifacts.validation
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    print(f"Loaded {len(artifacts.nodes)} point nodes from {paths.input_path}")
    print(f"Loaded {len(artifacts.physical_edges)} physical Carrier edges from {paths.edge_path}")
    print(
        f"Selected {len(design.core_ids)} cores, {len(design.aggregation_ids)} "
        f"aggregations, and {len(design.transit_ids)} transit PoPs"
    )
    print("Cores: " + ", ".join(nodes_by_id[node_id].name for node_id in design.core_ids))
    print(
        f"Designed {len(included_node_ids(design))} included nodes and "
        f"{len(design.access_edges) + len(design.physical_edge_keys)} selected edges "
        f"({design.metrics.access_miles + design.metrics.physical_miles:,.1f} total miles)"
    )
    print(
        "Validation: "
        f"connected={validation['connected']}, "
        f"min_degree={validation['min_distinct_neighbor_degree']}, "
        f"access_dual_homed={validation['access_nodes_with_two_aggregation_links']}, "
        f"agg_dual_homed_to_cores={validation['aggregations_dual_homed_to_cores']}, "
        f"cores_full_mesh={validation['cores_full_mesh']}"
    )
    for kind, path in outputs.items():
        print(f"Wrote {kind}: {path}")

def exit_code_for(validation: ValidationReport) -> int:
    """Return a non-zero exit code if any hard requirement was violated."""
    if not validation["aggregations_dual_homed_to_cores"]:
        names = ", ".join(
            entry["name"] for entry in validation["aggregations_missing_core_redundancy"]
        )
        print(
            f"error: aggregations lacking two node-disjoint paths to two cores: {names}",
            file=sys.stderr,
        )
        return 2
    if not validation["cores_full_mesh"]:
        print("error: core tier is not a full mesh", file=sys.stderr)
        return 2
    if validation["degree_deficient_nodes"]:
        print(
            "warning: validation found nodes with fewer than two distinct neighbors",
            file=sys.stderr,
        )
        return 2
    return 0

def main(argv: list[str] | None = None) -> int:
    """Compute the three-tier WAN design and write all output renderings."""
    args = build_parser().parse_args(argv)
    paths = cli_paths(args)
    params = params_from_args(args)
    mapbook = (
        paths.mapbook_pdf if paths.mapbook_pdf and paths.mapbook_pdf.exists() else None
    )
    sources = SourceFiles(paths.input_path, paths.edge_path, mapbook)
    try:
        artifacts = run_design(paths, params, not args.no_resilience_augmentation)
        outputs = write_outputs(paths.output_dir, sources, artifacts)
    except (ValueError, OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_summary(paths, artifacts, outputs)
    return exit_code_for(artifacts.validation)
