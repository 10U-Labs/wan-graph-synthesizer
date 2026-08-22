from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3

from synthesizer.codec import load_merged_carriers, load_off_net, load_regions, load_sites
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
    body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    return json.loads(body)


def _write_json(client: Any, key: str, body: Any) -> None:
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
    logger.info("Loading merged carriers and inputs for %s", tenant)
    carrier_pops, fiber_segments = load_merged_carriers(
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
        "Dual-homing %d sites over %d merged carrier links", len(graph), len(fiber_segments)
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
    logging.getLogger().setLevel(logging.INFO)
    client = boto3.client("s3", region_name="us-east-2")
    tenant = event["tenant"]
    status_key = f"tenants/{tenant}/wan-status.json"
    _write_json(client, status_key, {"status": "synthesizing", "tenant": tenant})
    logger.info("Build started for %s", tenant)
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
