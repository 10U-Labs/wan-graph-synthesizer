"""Fargate synthesizer entrypoint: build a tenant's WAN from the stored inputs.

A one-shot container task (TENANT + STORE_BUCKET in the environment): read the
substrate and the tenant's inputs from S3, run the whole design pipeline
(dual-home -> overrides -> synthesize -> finalize), and publish the WAN -- or record
a ``failed`` status when no valid WAN exists (``synthesize_two_tier_design`` raises
``ValueError``). ``main`` is invoked by the container command; there is no
compute-on-demand path.
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
    backbone_nodes,
    csp_nodes,
    edges,
    tenant_nodes,
    vertices,
)
from synthesizer.config import app_config_from_parts
from synthesizer.model import DesignArtifacts, SourceFiles
from synthesizer.synthesize import synthesize_two_tier_design
from synthesizer.output import design_payload
from synthesizer.overrides import apply_role_overrides
from synthesizer.stages import dual_home, finalize

logger = logging.getLogger(__name__)

# The tenant config resources, each its own stored document, assembled back into a
# single AppConfig. The two degrees are required; the rest default when empty.
CONFIG_RESOURCES = (
    "forced-backbone-nodes",
    "forced-connections",
    "prohibited-backbone-nodes",
    "prohibited-connections",
    "backbone-node-count",
    "backbone-mesh-degree",
    "access-homing-degree",
    "knobs",
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
    # Gate the backbone to data-center cities: a carrier PoP may be a backbone node
    # only where a colocation provider operates a cage. The set threads through
    # synthesis (eligibility) and the forced-pin/fabrication gates on DesignParams.
    params = replace(config.params, datacenter_cities=_datacenter_cities(client))
    graph = carrier_pops + locations + regions
    logger.info(
        "Dual-homing %d vertices over %d substrate edges", len(graph), len(physical_edges)
    )
    graph, physical_edges = dual_home(graph, physical_edges, params, off_net)
    graph, physical_edges, overrides = apply_role_overrides(
        graph,
        physical_edges,
        params,
        config.forced_connections,
        config.excluded_connections,
    )
    logger.info("Synthesizing two-tier design (this is the long step)")
    design = synthesize_two_tier_design(graph, physical_edges, params, overrides)
    logger.info("Finalizing and validating the design")
    graph, physical_edges, design, validation = finalize(
        graph, physical_edges, design, params
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
        "tenant-nodes": tenant_nodes(payload),
        "csp-nodes": csp_nodes(payload),
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
    # Any failure (an infeasible design raises ValueError, but an S3 read error or
    # an unforeseen bug can raise anything) must be recorded as the WAN's status
    # rather than crash the task and leave the tenant stuck "building" forever.
    try:
        wan = _build_wan(client, tenant)
    except Exception as exc:
        logger.warning("Build failed for %s: %s", tenant, exc)
        _write_json(client, status_key, {"status": "failed", "reason": str(exc)})
        return
    _write_json(client, f"tenants/{tenant}/wan.json", wan)
    _write_json(client, status_key, {"status": "ready"})
    logger.info("Build ready for %s", tenant)
