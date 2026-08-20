"""Synthesizer Lambda: build a tenant's WAN from the stored inputs.

Async-invoked by the dispatching Lambda with ``{"tenant": ...}`` (STORE_BUCKET in
the environment): read the substrate and the tenant's inputs from S3, run the whole
synthesis pipeline (dual-home -> overrides -> synthesize -> finalize), and publish the
WAN -- or record a ``fail`` status when no valid WAN exists
(``synthesize_two_tier`` raises ``ValueError``). A build is single-threaded
and finishes in seconds, well inside Lambda's 15-minute / 10 GB envelope.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3

from synthesizer.codec import load_off_net, load_regions, load_sites, load_substrate
from synthesizer.collections import (
    backbone_links,
    backbone_nodes,
    provider_nodes,
    paths,
    tenant_nodes,
    sites,
)
from synthesizer.config import app_config_from_parts
from synthesizer.coverage import CoverageReport, coverage_report
from synthesizer.input_graph import Site
from synthesizer.model import (
    Synthesis,
    SynthesisArtifacts,
    SynthesisParams,
    SourceFiles,
    ValidationReport,
    is_carrier_pop,
)
from synthesizer.synthesize import synthesize_two_tier
from synthesizer.output import synthesis_payload
from synthesizer.overrides import apply_role_overrides
from synthesizer.stages import dual_home, finalize

logger = logging.getLogger(__name__)

# The tenant config resources, each its own stored document, assembled back into a
# single AppConfig. The two degrees and the ``knobs`` coverage target are required;
# the rest default when empty. ``settings`` holds the implementation dials, and takes
# precedence over ``knobs`` where a key appears in both.
CONFIG_RESOURCES = (
    "forced-backbone-nodes",
    "forced-paths",
    "forced-homes",
    "prohibited-backbone-nodes",
    "prohibited-paths",
    "degree-exempt-backbone-nodes",
    "backbone-node-count",
    "backbone-number-of-diverse-paths",
    "access-homing-degree",
    "convergence-promotion",
    "knobs",
    "settings",
    "label",
)


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
    graph: list[Site],
    synthesis: Synthesis,
    validation: ValidationReport,
    params: SynthesisParams,
    tenant: str,
) -> dict[str, Any]:
    """Measure -- and log -- what the finished synthesis did about the tenant's requirements.

    Coverage is measured off the delivered network rather than reported by the search that
    built it, so a synthesis that grew until nothing was left to seat is told apart from one
    that met the target by the only evidence an operator has: where the sites ended up.

    The backup path multiple is echoed rather than measured, because it is not a thing a
    synthesis can fall short of by degrees the way a coverage target is. What a reader needs
    from it is which bound the links in front of them were drawn under, since the operator
    can move it and a network published before they did is built to the old one.

    How many independently failing links each site was asked for, and which sites did not
    get that many, travel with it. A count computed too high asks a site for a link the
    backup path multiple will not let the mesh lay, and the synthesis then reports a shortfall no
    fiber an operator buys can close (GitHub issue #45). None of that reaches the published
    collections -- they carry the links that were drawn, not the links that were asked for
    -- so a reader outside the build could see the network was thin and never see that the
    build had already said so.

    ``backbone_lower_bound_miles`` travels with them because it is the only figure that
    says whether the fiber an operator is paying for is close to the least this network
    could have been built with. It is the answer to the linear-programming relaxation the
    fiber was chosen by (see :mod:`synthesizer.survivable`), so no synthesis meeting this
    tenant's requirements runs fewer miles than that -- which is what lets a reader outside
    the build hold the published network to it, and what
    ``test_delivered_syntheses`` does against all five live maps.
    """
    coverage: CoverageReport = coverage_report(
        synthesis.backbone_ids,
        [site for site in graph if not is_carrier_pop(site)],
        {site.id: site for site in graph},
        params.tuning.backbone_coverage_target_miles,
    )
    logger.info("Coverage delivered for %s: %s", tenant, coverage)
    short = validation["backbone_mesh_independence_deficient"]
    logger.info("Sites short of their diverse-path target for %s: %s", tenant, short)
    return {
        "coverage": coverage,
        "max_backup_path_multiple": params.tuning.backbone_max_backup_path_multiple,
        "backbone_lower_bound_miles": round(synthesis.metrics.backbone_lower_bound_miles, 3),
        "diverse_paths": {
            "number_of_diverse_paths": params.tuning.backbone_number_of_diverse_paths,
            "ceilings": validation["backbone_diverse_paths_ceilings"],
            "short": short,
        },
    }


def _build_wan(client: Any, tenant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the whole synthesis pipeline for one tenant; shape its WAN collections.

    What the synthesis delivered against the tenant's requirements comes back beside the
    collections (see :func:`_delivered`), because a caller reading only the published WAN
    would have no way to tell a build that met them from one that did not, nor which
    requirements it was held to in the first place.
    """
    logger.info("Loading substrate and inputs for %s", tenant)
    carrier_pops, fiber_segments = load_substrate(
        _read_json(client, "carriers/merge/pops.json"),
        _read_json(client, "carriers/merge/fiber-segments.json"),
    )
    locations = load_sites(_read_json(client, f"tenants/{tenant}/locations.json"))
    regions = load_regions(_read_json(client, f"tenants/{tenant}/provider-regions.json"))
    off_net = load_off_net(_read_json(client, f"tenants/{tenant}/off-net.json"))
    parts = {
        resource: _read_json(client, f"tenants/{tenant}/{resource}.json")
        for resource in CONFIG_RESOURCES
    }
    config = app_config_from_parts(parts)
    params = config.params
    graph = carrier_pops + locations + regions
    logger.info(
        "Dual-homing %d sites over %d substrate links", len(graph), len(fiber_segments)
    )
    graph, fiber_segments = dual_home(graph, fiber_segments, params, off_net)
    graph, fiber_segments, overrides = apply_role_overrides(
        graph, fiber_segments, params, config.links
    )
    logger.info("Synthesizing two-tier synthesis (this is the long step)")
    synthesis = synthesize_two_tier(graph, fiber_segments, params, overrides)
    logger.info("Finalizing and validating the synthesis")
    graph, fiber_segments, synthesis, validation = finalize(
        graph, fiber_segments, synthesis, params, overrides.degree_exempt_backbone_ids
    )
    payload = synthesis_payload(
        SourceFiles((), Path("store")),
        SynthesisArtifacts(graph, fiber_segments, synthesis, validation),
    )
    logger.info("Publishing WAN for %s", tenant)
    return {
        "sites": sites(payload),
        "paths": paths(payload),
        "backbone-nodes": backbone_nodes(payload),
        "backbone-links": backbone_links(payload),
        "tenant-nodes": tenant_nodes(payload),
        "provider-nodes": provider_nodes(payload),
    }, _delivered(graph, synthesis, validation, params, tenant)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Build the tenant's WAN and publish it, or record why it failed.

    The dispatcher async-invokes this with ``{"tenant": ...}``. The status is moved to
    ``synthesizing`` first -- the in-progress marker the GET reads -- then ``success``
    once the WAN is published, or ``fail`` if the build raises.

    A ``success`` status carries the coverage the synthesis delivered. Growth toward the
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
    # Any failure (an infeasible synthesis raises ValueError, but an S3 read error or
    # an unforeseen bug can raise anything) must be recorded as the WAN's status
    # rather than crash the invocation and leave the tenant stuck "synthesizing" forever.
    try:
        wan, delivered = _build_wan(client, tenant)
    except Exception as exc:
        logger.warning("Build failed for %s: %s", tenant, exc)
        _write_json(client, status_key, {"status": "fail", "reason": str(exc)})
        return {"status": "fail", "tenant": tenant}
    _write_json(client, f"tenants/{tenant}/wan.json", wan)
    _write_json(client, status_key, {"status": "success", **delivered})
    logger.info("Build succeeded for %s", tenant)
    return {"status": "success", "tenant": tenant}
