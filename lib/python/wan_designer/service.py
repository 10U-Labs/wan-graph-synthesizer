"""Run the three-tier design pipeline end to end from a resolved config.

``run_design`` chains the design stages (dual-home -> overrides -> optimize ->
finalize) into the single artifacts bundle the tests assert against. Production
runs the same stages inline in the Fargate optimizer entrypoint; this helper is
the shared driver for the unit and integration suites.
"""

from __future__ import annotations

import logging

from wan_designer import stages
from wan_designer.model import (
    DesignArtifacts,
    DesignParams,
    DesignPaths,
    ForcedConnection,
    carrier_role,
    is_carrier_pop,
)
from wan_designer.offnet import load_off_net_sites
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.overrides import apply_role_overrides

logger = logging.getLogger(__name__)


def run_design(
    paths: DesignPaths,
    params: DesignParams,
    augment: bool,
    forced_connections: tuple[ForcedConnection, ...] = (),
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> DesignArtifacts:
    """Load inputs, optimize the three-tier design, and validate it."""
    vertices, physical_edges = stages.load_inputs(paths)
    off_net_sites = load_off_net_sites(paths.off_net_path) if paths.off_net_path else []
    vertices, physical_edges = stages.dual_home(
        vertices, physical_edges, params, off_net_sites
    )
    roles = {pop.id: carrier_role(pop) for pop in vertices if is_carrier_pop(pop)}
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, forced_connections, excluded_connections
    )
    logger.info(
        "Loaded %d vertices and %d physical edges; starting optimization",
        len(vertices), len(physical_edges),
    )
    design = optimize_three_tier_design(vertices, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating the design")
    vertices, physical_edges, design, validation = stages.finalize(
        vertices, physical_edges, design, params, augment
    )
    return DesignArtifacts(vertices, physical_edges, design, validation)
