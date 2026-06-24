"""Fargate synthesizer entrypoint: build a tenant's WAN from the stored inputs.

A one-shot container task (TENANT + STORE_BUCKET in the environment): read the
substrate and the tenant's inputs from S3, run the whole design pipeline
(dual-home -> overrides -> synthesize -> finalize), and publish the WAN -- or record
a ``failed`` status when no valid WAN exists (``synthesize_three_tier_design`` raises
``ValueError``). ``main`` is invoked by the container command; there is no
compute-on-demand path.
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
    access_nodes,
    aggregation_points,
    core_nodes,
    edges,
    vertices,
)
from synthesizer.config import app_config_from_parts
from synthesizer.model import DesignArtifacts, SourceFiles
from synthesizer.synthesize import synthesize_three_tier_design
from synthesizer.output import design_payload
from synthesizer.overrides import apply_role_overrides
from synthesizer.stages import dual_home, finalize

logger = logging.getLogger(__name__)

# The tenant config resources, each its own stored document, assembled back into a
# single AppConfig. The three degrees are required; the rest default when empty.
CONFIG_RESOURCES = (
    "forced-core-nodes",
    "forced-aggregation-points",
    "forced-connections",
    "prohibited-core-nodes",
    "prohibited-aggregation-points",
    "prohibited-connections",
    "core-node-count",
    "core-mesh-degree",
    "aggregation-homing-degree",
    "access-homing-degree",
    "knobs",
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


def _build_wan(client: Any, tenant: str) -> dict[str, Any]:
    """Run the whole design pipeline for one tenant; shape its WAN collections."""
    logger.info("Loading substrate and inputs for %s", tenant)
    carrier_pops, physical_edges = load_substrate(
        _read_json(client, "carriers/merge/vertices.json"),
        _read_json(client, "carriers/merge/edges.json"),
    )
    locations = load_sites(_read_json(client, f"tenants/{tenant}/locations.json"))
    regions = load_regions(_read_json(client, f"tenants/{tenant}/csp-regions.json"))
    off_net = load_off_net(_read_json(client, f"tenants/{tenant}/off-net.json"))
    parts = {
        resource: _read_json(client, f"tenants/{tenant}/{resource}.json")
        for resource in CONFIG_RESOURCES
    }
    config = app_config_from_parts(parts)
    graph = carrier_pops + locations + regions
    logger.info(
        "Dual-homing %d vertices over %d substrate edges", len(graph), len(physical_edges)
    )
    graph, physical_edges = dual_home(graph, physical_edges, config.params, off_net)
    graph, physical_edges, overrides = apply_role_overrides(
        graph,
        physical_edges,
        config.params,
        config.forced_connections,
        config.excluded_connections,
    )
    logger.info("Synthesizing three-tier design (this is the long step)")
    design = synthesize_three_tier_design(graph, physical_edges, config.params, overrides)
    logger.info("Finalizing and validating the design")
    graph, physical_edges, design, validation = finalize(
        graph, physical_edges, design, config.params
    )
    payload = design_payload(
        SourceFiles((), Path("store")),
        DesignArtifacts(graph, physical_edges, design, validation),
    )
    logger.info("Publishing WAN for %s", tenant)
    return {
        "vertices": vertices(payload),
        "edges": edges(payload),
        "core-nodes": core_nodes(payload),
        "aggregation-points": aggregation_points(payload),
        "access-nodes": access_nodes(payload),
    }


def main() -> None:
    """Build the tenant's WAN and publish it, or record why it failed."""
    # Emit INFO progress to stdout so a long build is observable in CloudWatch
    # (the default root level is WARNING, which would drop every progress line).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = boto3.client("s3", region_name="us-east-2")
    tenant = os.environ["TENANT"]
    status_key = f"tenants/{tenant}/wan-status.json"
    # A Spot reclaim kills this task without warning; leave the status at "building"
    # so the ecs-task-stopped handler can relaunch it. Only an in-process failure
    # (below) records "failed".
    _write_json(client, status_key, {"status": "building", "tenant": tenant})
    logger.info("Build started for %s", tenant)
    # Any failure (infeasible design, or an unexpected error) must be recorded as
    # the WAN's status rather than crash the task and leave it stuck "creating".
    try:
        wan = _build_wan(client, tenant)
    except Exception as exc:
        logger.warning("Build failed for %s: %s", tenant, exc)
        _write_json(client, status_key, {"status": "failed", "reason": str(exc)})
        return
    _write_json(client, f"tenants/{tenant}/wan.json", wan)
    _write_json(client, status_key, {"status": "ready"})
    logger.info("Build ready for %s", tenant)
