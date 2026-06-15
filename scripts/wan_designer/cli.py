"""Command-line interface for the three-tier WAN designer."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wan_designer.config import AppConfig, default_config, load_config
from wan_designer.model import (
    CliPaths,
    DesignArtifacts,
    DesignParams,
    PhysicalEdge,
    SourceFiles,
    ValidationReport,
    carrier_role,
    is_carrier_pop,
)
from wan_designer.parsing import load_carrier_edges, load_vertices
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.validation import (
    augment_physical_resilience,
    included_vertex_ids,
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
        help="Vertices CSV (name,latitude,longitude,tenant,kind,description). "
        "Overrides the config's vertices file.",
    )
    parser.add_argument(
        "--carrier-edges",
        default=None,
        help="CSV of physical Carrier mapbook route edges.",
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
        help="Exact number of core vertices. Overrides the config's core_count.",
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
        help="Allow mapbook ROADM vertices to be selected as aggregation/core points.",
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
        vertices_path=_path_or(args.input, base.vertices_path),
        edge_path=_path_or(args.carrier_edges, base.edge_path),
        mapbook_pdf=_optional_path_override(args.mapbook_pdf, base.mapbook_pdf),
        output_dir=_path_or(args.output_dir, base.output_dir),
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
    vertices = load_vertices(paths.vertices_path)
    if not vertices:
        raise ValueError(f"No vertices found in {paths.vertices_path}")
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    physical_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in (paths.edge_path, *paths.regional_edge_paths):
        physical_edges.update(load_carrier_edges(edge_path, carrier_pops))
    roles = {pop.id: carrier_role(pop) for pop in carrier_pops}
    vertices, physical_edges, overrides = apply_role_overrides(vertices, physical_edges, params)
    logger.info(
        "Loaded %d vertices and %d physical edges; starting optimization",
        len(vertices), len(physical_edges),
    )
    design = optimize_three_tier_design(vertices, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating and writing outputs")
    if augment:
        design = augment_physical_resilience(vertices, physical_edges, design)
    validation = validate_design(vertices, design)
    return DesignArtifacts(vertices, physical_edges, design, validation)

def print_summary(
    paths: CliPaths, artifacts: DesignArtifacts, outputs: dict[str, Path]
) -> None:
    """Print a human-readable summary of the computed design."""
    design = artifacts.design
    validation = artifacts.validation
    vertices_by_id = {vertex.id: vertex for vertex in artifacts.vertices}
    print(f"Loaded {len(artifacts.vertices)} vertices from {paths.vertices_path}")
    print(f"Loaded {len(artifacts.physical_edges)} physical Carrier edges from {paths.edge_path}")
    print(
        f"Selected {len(design.core_ids)} cores, {len(design.aggregation_ids)} "
        f"aggregations, and {len(design.transit_ids)} transit PoPs"
    )
    print("Cores: " + ", ".join(vertices_by_id[vertex_id].name for vertex_id in design.core_ids))
    print(
        f"Designed {len(included_vertex_ids(design))} included vertices and "
        f"{len(design.access_edges) + len(design.physical_edge_keys)} selected edges "
        f"({design.metrics.access_miles + design.metrics.physical_miles:,.1f} total miles)"
    )
    print(
        "Validation: "
        f"connected={validation['connected']}, "
        f"min_degree={validation['min_distinct_neighbor_degree']}, "
        f"access_dual_homed={validation['access_vertices_with_two_aggregation_links']}, "
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
            f"error: aggregations lacking two vertex-disjoint paths to two cores: {names}",
            file=sys.stderr,
        )
        return 2
    if not validation["cores_full_mesh"]:
        print("error: core tier is not a full mesh", file=sys.stderr)
        return 2
    if validation["degree_deficient_vertices"]:
        print(
            "warning: validation found vertices with fewer than two distinct neighbors",
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
        sources = SourceFiles(paths.vertices_path, paths.edge_path, mapbook)
        outputs = write_outputs(paths.output_dir, sources, artifacts)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_summary(paths, artifacts, outputs)
    return exit_code_for(artifacts.validation)
