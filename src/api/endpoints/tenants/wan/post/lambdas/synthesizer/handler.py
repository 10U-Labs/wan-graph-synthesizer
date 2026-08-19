"""Synthesizer Lambda: build a tenant's WAN from the stored inputs.

Async-invoked by the dispatching Lambda with ``{"tenant": ...}`` (STORE_BUCKET in
the environment): read the substrate and the tenant's inputs from S3, run the whole
design pipeline (dual-home -> overrides -> synthesize -> finalize), and publish the
WAN -- or record a ``failed`` status when no valid WAN exists
(``synthesize_two_tier_design`` raises ``ValueError``). A build is single-threaded
and finishes in seconds, well inside Lambda's 15-minute / 10 GB envelope.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import boto3

from synthesizer.codec import load_off_net, load_regions, load_sites, load_substrate
from synthesizer.collections import (
    backbone_links,
    backbone_nodes,
    provider_nodes,
    edges,
    tenant_nodes,
    vertices,
)
from synthesizer.config import app_config_from_parts
from synthesizer.coverage import CoverageReport, coverage_report
from synthesizer.input_graph import Vertex
from synthesizer.model import (
    Design,
    DesignArtifacts,
    DesignParams,
    SourceFiles,
    ValidationReport,
    is_carrier_pop,
)
from synthesizer.synthesize import synthesize_two_tier_design
from synthesizer.output import design_payload
from synthesizer.overrides import apply_role_overrides
from synthesizer.stages import dual_home, finalize

logger = logging.getLogger(__name__)

# The tenant config resources, each its own stored document, assembled back into a
# single AppConfig. The two degrees and the ``knobs`` coverage target are required;
# the rest default when empty. ``settings`` holds the implementation dials, and takes
# precedence over ``knobs`` where a key appears in both.
CONFIG_RESOURCES = (
    "forced-backbone-nodes",
    "forced-connections",
    "forced-homes",
    "prohibited-backbone-nodes",
    "prohibited-connections",
    "degree-exempt-backbone-nodes",
    "backbone-node-count",
    "backbone-number-of-diverse-paths",
    "access-homing-degree",
    "backbone-placement",
    "convergence-promotion",
    "knobs",
    "settings",
    "label",
)


def _datacenter_cities(client: Any) -> frozenset[tuple[str, str]]:
    """The ``(municipality, state)`` cities a colocation provider operates a cage in.

    Read from the merged data-center facilities; a carrier PoP may serve as a backbone
    node only at one of these cities (the gate threaded onto ``DesignParams``).
    """
    rows = _read_json(client, "data-centers/merge/vertices.json")
    return frozenset((row["municipality"], row["state"]) for row in rows)


def _read_json(client: Any, key: str) -> Any:
    """Read and decode a JSON object from the store."""
    body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    return json.loads(body)


def _write_json(client: Any, key: str, body: Any) -> None:
    """Encode and write a JSON object to the store."""
    client.put_object(
        Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(body).encode()
    )


def _delivered(
    graph: list[Vertex],
    design: Design,
    validation: ValidationReport,
    params: DesignParams,
    tenant: str,
) -> dict[str, Any]:
    """Measure -- and log -- what the finished design did about the tenant's requirements.

    Coverage is measured off the delivered network rather than reported by the search that
    built it, so a design that grew until nothing was left to seat is told apart from one
    that met the target by the only evidence an operator has: where the sites ended up.

    The backup path multiple is echoed rather than measured, because it is not a thing a
    design can fall short of by degrees the way a coverage target is. What a reader needs
    from it is which bound the links in front of them were drawn under, since the operator
    can move it and a network published before they did is built to the old one.

    How many independently failing links each site was asked for, and which sites did not
    get that many, travel with it. A count computed too high asks a site for a link the
    backup path multiple will not let the mesh lay, and the design then reports a shortfall no
    fiber an operator buys can close (GitHub issue #45). None of that reaches the published
    collections -- they carry the links that were drawn, not the links that were asked for
    -- so a reader outside the build could see the network was thin and never see that the
    build had already said so.

    ``backbone_lower_bound_miles`` travels with them because it is the only figure that
    says whether the fiber an operator is paying for is close to the least this network
    could have been built with. It is the answer to the linear-programming relaxation the
    fiber was chosen by (see :mod:`synthesizer.survivable`), so no design meeting this
    tenant's requirements runs fewer miles than that -- which is what lets a reader outside
    the build hold the published network to it, and what
    ``test_delivered_designs`` does against all six live maps.
    """
    coverage: CoverageReport = coverage_report(
        design.backbone_ids,
        [vertex for vertex in graph if not is_carrier_pop(vertex)],
        {vertex.id: vertex for vertex in graph},
        params.tuning.backbone_coverage_target_miles,
    )
    logger.info("Coverage delivered for %s: %s", tenant, coverage)
    short = validation["backbone_mesh_independence_deficient"]
    logger.info("Sites short of their diverse-path target for %s: %s", tenant, short)
    return {
        "coverage": coverage,
        "max_backup_path_multiple": params.tuning.backbone_max_backup_path_multiple,
        "backbone_lower_bound_miles": round(design.metrics.backbone_lower_bound_miles, 3),
        "diverse_paths": {
            "number_of_diverse_paths": params.tuning.backbone_number_of_diverse_paths,
            "ceilings": validation["backbone_diverse_paths_ceilings"],
            "short": short,
        },
    }


def _build_wan(client: Any, tenant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the whole design pipeline for one tenant; shape its WAN collections.

    What the design delivered against the tenant's requirements comes back beside the
    collections (see :func:`_delivered`), because a caller reading only the published WAN
    would have no way to tell a build that met them from one that did not, nor which
    requirements it was held to in the first place.
    """
    logger.info("Loading substrate and inputs for %s", tenant)
    carrier_pops, physical_edges = load_substrate(
        _read_json(client, "carriers/merge/vertices.json"),
        _read_json(client, "carriers/merge/edges.json"),
    )
    locations = load_sites(_read_json(client, f"tenants/{tenant}/locations.json"))
    regions = load_regions(_read_json(client, f"tenants/{tenant}/provider-regions.json"))
    off_net = load_off_net(_read_json(client, f"tenants/{tenant}/off-net.json"))
    parts = {
        resource: _read_json(client, f"tenants/{tenant}/{resource}.json")
        for resource in CONFIG_RESOURCES
    }
    config = app_config_from_parts(parts)
    # Gate the backbone to data-center cities when the tenant opts in: a carrier PoP may
    # be a backbone node only where a colocation provider operates a cage. The set threads
    # through synthesis (eligibility) and the forced-pin/fabrication gates on DesignParams.
    # In the operator's free-for-all (restrict off) the gate is None and any PoP is eligible.
    params = replace(
        config.params,
        datacenter_cities=(
            _datacenter_cities(client) if config.restrict_backbone_to_datacenters else None
        ),
    )
    graph = carrier_pops + locations + regions
    logger.info(
        "Dual-homing %d vertices over %d substrate edges", len(graph), len(physical_edges)
    )
    graph, physical_edges = dual_home(graph, physical_edges, params, off_net)
    graph, physical_edges, overrides = apply_role_overrides(
        graph, physical_edges, params, config.links
    )
    logger.info("Synthesizing two-tier design (this is the long step)")
    design = synthesize_two_tier_design(graph, physical_edges, params, overrides)
    logger.info("Finalizing and validating the design")
    graph, physical_edges, design, validation = finalize(
        graph, physical_edges, design, params, overrides.degree_exempt_backbone_ids
    )
    payload = design_payload(
        SourceFiles((), Path("store")),
        DesignArtifacts(graph, physical_edges, design, validation),
    )
    logger.info("Publishing WAN for %s", tenant)
    return {
        "vertices": vertices(payload),
        "edges": edges(payload),
        "backbone-nodes": backbone_nodes(payload),
        "backbone-links": backbone_links(payload),
        "tenant-nodes": tenant_nodes(payload),
        "provider-nodes": provider_nodes(payload),
    }, _delivered(graph, design, validation, params, tenant)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Build the tenant's WAN and publish it, or record why it failed.

    The dispatcher async-invokes this with ``{"tenant": ...}``. The status is moved to
    ``synthesizing`` first -- the in-progress marker the GET reads -- then ``success``
    once the WAN is published, or ``failed`` if the build raises.

    A ``success`` status carries the coverage the design delivered. Growth toward the
    operator's target can stop short of it, and a build that gave up used to be published
    under the same one word as a build that met it, so nothing downstream could tell them
    apart without reading the synthesizer's own log.

    It carries the backup path multiple the build ran under for the same reason read
    forward in time: the operator can move it, and until the tenant is rebuilt the published
    network is one built to the old one. A reader comparing the network against the config
    git now holds needs to know which of the two it is looking at, and nothing in the
    collections themselves says so.

    It carries what each site was asked for and which sites came up short for a third
    reason: those are the build's own findings about the network, and they are the only
    place a shortfall appears at all (see :func:`_delivered`).
    """
    # Surface INFO progress in CloudWatch (the Lambda runtime defaults the root logger
    # to WARNING, which would drop every progress line).
    logging.getLogger().setLevel(logging.INFO)
    client = boto3.client("s3", region_name="us-east-2")
    tenant = event["tenant"]
    status_key = f"tenants/{tenant}/wan-status.json"
    _write_json(client, status_key, {"status": "synthesizing", "tenant": tenant})
    logger.info("Build started for %s", tenant)
    # Any failure (an infeasible design raises ValueError, but an S3 read error or
    # an unforeseen bug can raise anything) must be recorded as the WAN's status
    # rather than crash the invocation and leave the tenant stuck "synthesizing" forever.
    try:
        wan, delivered = _build_wan(client, tenant)
    except Exception as exc:
        logger.warning("Build failed for %s: %s", tenant, exc)
        _write_json(client, status_key, {"status": "failed", "reason": str(exc)})
        return {"status": "failed", "tenant": tenant}
    _write_json(client, f"tenants/{tenant}/wan.json", wan)
    _write_json(client, status_key, {"status": "success", **delivered})
    logger.info("Build succeeded for %s", tenant)
    return {"status": "success", "tenant": tenant}
