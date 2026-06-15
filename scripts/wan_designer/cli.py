"""Command-line interface for the three-tier WAN designer."""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from wan_designer.config import AppConfig, default_config, load_config
from wan_designer.model import (
    CliPaths,
    DesignArtifacts,
    DesignParams,
    SourceFiles,
    ValidationReport,
)
from wan_designer.parsing import (
    load_carrier_edges,
    load_nodes,
    load_pop_roles,
    load_regional_networks,
)
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.validation import (
    augment_physical_resilience,
    included_node_ids,
    validate_design,
)
from wan_designer.output import write_outputs

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute a three-tier core/aggregation/access WAN over the "
            "Carrier mapbook edge graph."
        )
    )
    parser.add_argument(
        "--config",
        default=None,
        help="YAML config file (e.g. etc/config.yml). Provides defaults; flags override it.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Input KMZ or KML file. Overrides the config's mapbook.",
    )
    parser.add_argument(
        "--carrier-edges",
        default=None,
        help="CSV of physical Carrier mapbook route edges.",
    )
    parser.add_argument(
        "--pop-roles",
        default=None,
        help="Optional CSV of Carrier PoP roles; pass empty to disable.",
    )
    parser.add_argument(
        "--mapbook-pdf",
        default=None,
        help="Optional source PDF path recorded in JSON output.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for JSON, CSV, KML, and DOT outputs.",
    )
    parser.add_argument(
        "--core-count",
        type=int,
        default=None,
        help="Exact number of core nodes. Overrides the config's core_count.",
    )
    parser.add_argument(
        "--regional-nodes",
        default=None,
        help="Regional carrier node coordinates; pass empty to disable regional carriers.",
    )
    parser.add_argument(
        "--regional-edges",
        nargs="*",
        default=None,
        help="Regional carrier edge files stitched into the Lumen graph.",
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
    parser.add_argument(
        "--force-core",
        action="append",
        default=[],
        metavar="POP_NAME",
        help="Pin a PoP (by name) as a core; repeatable. Pin it as an aggregation too "
        "to co-locate a core and an aggregation in the one facility.",
    )
    parser.add_argument(
        "--force-aggregation",
        action="append",
        default=[],
        metavar="POP_NAME",
        help="Pin a PoP (by name) as an aggregation; repeatable.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="POP_NAME",
        help="Bar a PoP (by name) from being a core, aggregation, or access home; repeatable.",
    )
    return parser

def load_app_config(args: argparse.Namespace) -> AppConfig:
    """Load the base config named by ``--config``, or the built-in defaults."""
    if args.config is not None:
        return load_config(Path(args.config))
    return default_config()

def _path_or(value: str | None, fallback: Path) -> Path:
    """A provided non-empty path string overrides the config; else keep config."""
    return Path(value) if value else fallback

def _optional_path_override(value: str | None, fallback: Path | None) -> Path | None:
    """None keeps the config path; an empty string disables it; else override it."""
    if value is None:
        return fallback
    return Path(value) if value else None

def resolve_paths(config: AppConfig, args: argparse.Namespace) -> CliPaths:
    """Overlay any path flags onto the config's file paths."""
    base = config.paths
    regional_edges = (
        tuple(Path(path) for path in args.regional_edges)
        if args.regional_edges is not None
        else base.regional_edge_paths
    )
    return CliPaths(
        input_path=_path_or(args.input, base.input_path),
        edge_path=_path_or(args.carrier_edges, base.edge_path),
        role_path=_optional_path_override(args.pop_roles, base.role_path),
        mapbook_pdf=_optional_path_override(args.mapbook_pdf, base.mapbook_pdf),
        output_dir=_path_or(args.output_dir, base.output_dir),
        regional_node_path=_optional_path_override(args.regional_nodes, base.regional_node_path),
        regional_edge_paths=regional_edges,
    )

def resolve_params(config: AppConfig, args: argparse.Namespace) -> DesignParams:
    """Overlay any design flags onto the config's design parameters."""
    base = config.params
    return DesignParams(
        core_count=args.core_count if args.core_count is not None else base.core_count,
        allow_roadm_aggregation=base.allow_roadm_aggregation or args.allow_roadm_aggregation,
        forced_core_names=tuple(args.force_core) or base.forced_core_names,
        forced_aggregation_names=tuple(args.force_aggregation) or base.forced_aggregation_names,
        excluded_names=tuple(args.exclude) or base.excluded_names,
        tuning=base.tuning,
    )

def run_design(paths: CliPaths, params: DesignParams, augment: bool) -> DesignArtifacts:
    """Load inputs, optimize the design, and validate it."""
    nodes = load_nodes(paths.input_path)
    if not nodes:
        raise ValueError(f"No point placemarks found in {paths.input_path}")
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    physical_edges = load_carrier_edges(paths.edge_path, carrier_pops)
    roles = load_pop_roles(paths.role_path, carrier_pops)
    if paths.regional_node_path is not None:
        regional_nodes, regional_edges, regional_roles = load_regional_networks(
            paths.regional_node_path, list(paths.regional_edge_paths), carrier_pops
        )
        nodes = nodes + regional_nodes
        physical_edges = {**physical_edges, **regional_edges}
        roles = {**roles, **regional_roles}
    nodes, physical_edges, overrides = apply_role_overrides(nodes, physical_edges, params)
    logger.info(
        "Loaded %d nodes and %d physical edges; starting optimization",
        len(nodes), len(physical_edges),
    )
    design = optimize_three_tier_design(nodes, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating and writing outputs")
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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S"
    )
    args = build_parser().parse_args(argv)
    try:
        config = load_app_config(args)
        paths = resolve_paths(config, args)
        params = resolve_params(config, args)
        augment = config.resilience_augmentation and not args.no_resilience_augmentation
        artifacts = run_design(paths, params, augment)
        mapbook = (
            paths.mapbook_pdf if paths.mapbook_pdf and paths.mapbook_pdf.exists() else None
        )
        sources = SourceFiles(paths.input_path, paths.edge_path, mapbook)
        outputs = write_outputs(paths.output_dir, sources, artifacts)
    except (ValueError, OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_summary(paths, artifacts, outputs)
    return exit_code_for(artifacts.validation)
