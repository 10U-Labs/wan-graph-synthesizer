"""Fargate synthesizer entrypoint: build a customer's WAN from the stored inputs.

A one-shot container task (CUSTOMER + STORE_BUCKET in the environment): read the
substrate and the customer's inputs from S3, run the whole design pipeline
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

from wan_graph.codec import load_input_graph
from wan_synthesizer.collections import (
    access_nodes,
    aggregation_points,
    core_nodes,
    edges,
    vertices,
)
from wan_synthesizer.config import app_config_from_parts
from wan_synthesizer.model import DesignArtifacts, SourceFiles
from wan_synthesizer.synthesize import synthesize_three_tier_design
from wan_synthesizer.output import design_payload
from wan_synthesizer.overrides import apply_role_overrides
from wan_synthesizer.stages import dual_home, finalize

logger = logging.getLogger(__name__)

# The customer config resources, each its own stored document, assembled back into a
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


def _build_wan(client: Any, customer: str) -> dict[str, Any]:
    """Run the whole design pipeline for one customer; shape its WAN collections."""
    logger.info("Loading substrate and inputs for %s", customer)
    carrier_pops, physical_edges = load_input_graph(
        _read_json(client, "merge/substrate.json")
    )
    locations, _ = load_input_graph(
        _read_json(client, f"customers/{customer}/locations.json")
    )
    regions, _ = load_input_graph(
        _read_json(client, f"customers/{customer}/csp-regions.json")
    )
    off_net, _ = load_input_graph(
        _read_json(client, f"customers/{customer}/off-net.json")
    )
    parts = {
        resource: _read_json(client, f"customers/{customer}/{resource}.json")
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
    logger.info("Publishing WAN for %s", customer)
    return {
        "vertices": vertices(payload),
        "edges": edges(payload),
        "core-nodes": core_nodes(payload),
        "aggregation-points": aggregation_points(payload),
        "access-nodes": access_nodes(payload),
    }


def main() -> None:
    """Build the customer's WAN and publish it, or record why it failed."""
    # Emit INFO progress to stdout so a long build is observable in CloudWatch
    # (the default root level is WARNING, which would drop every progress line).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = boto3.client("s3", region_name="us-east-2")
    customer = os.environ["CUSTOMER"]
    status_key = f"customers/{customer}/wan-status.json"
    # Mark the task as actively building (distinct from the handler's "creating",
    # which only means a create was requested) so a stuck task is observable.
    _write_json(client, status_key, {"status": "building", "customer": customer})
    logger.info("Build started for %s", customer)
    # Any failure (infeasible design, or an unexpected error) must be recorded as
    # the WAN's status rather than crash the task and leave it stuck "creating".
    try:
        wan = _build_wan(client, customer)
    except Exception as exc:
        logger.warning("Build failed for %s: %s", customer, exc)
        _write_json(client, status_key, {"status": "failed", "reason": str(exc)})
        return
    _write_json(client, f"customers/{customer}/wan.json", wan)
    _write_json(client, status_key, {"status": "ready"})
    logger.info("Build ready for %s", customer)
