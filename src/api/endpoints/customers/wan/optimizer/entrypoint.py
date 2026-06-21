"""Fargate optimizer entrypoint: build a customer's WAN from the stored inputs.

A one-shot container task (CUSTOMER + STORE_BUCKET in the environment): read the
substrate and the customer's inputs from S3, run the whole design pipeline
(dual-home -> overrides -> optimize -> finalize), and publish the WAN -- or record
a ``failed`` status when no valid WAN exists (``optimize_three_tier_design`` raises
``ValueError``). ``main`` is invoked by the container command; there is no
compute-on-demand path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import boto3

from wan_graph.graph_collections import (
    access_nodes,
    aggregation_points,
    core_nodes,
    edges,
    load_input_graph,
    vertices,
)
from wan_graph.model import (
    DesignArtifacts,
    SourceFiles,
)
from wan_designer.config import app_config_from_parts
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.output import design_payload
from wan_designer.overrides import apply_role_overrides
from wan_designer.stages import dual_home, finalize

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
    graph, physical_edges = dual_home(graph, physical_edges, config.params, off_net)
    graph, physical_edges, overrides = apply_role_overrides(
        graph,
        physical_edges,
        config.params,
        config.forced_connections,
        config.excluded_connections,
    )
    design = optimize_three_tier_design(graph, physical_edges, config.params, overrides)
    graph, physical_edges, design, validation = finalize(
        graph, physical_edges, design, config.params
    )
    payload = design_payload(
        SourceFiles((), Path("store")),
        DesignArtifacts(graph, physical_edges, design, validation),
    )
    return {
        "vertices": vertices(payload),
        "edges": edges(payload),
        "core-nodes": core_nodes(payload),
        "aggregation-points": aggregation_points(payload),
        "access-nodes": access_nodes(payload),
    }


def main() -> None:
    """Build the customer's WAN and publish it, or record why it failed."""
    client = boto3.client("s3", region_name="us-east-2")
    customer = os.environ["CUSTOMER"]
    status_key = f"customers/{customer}/wan-status.json"
    # Mark the task as actively building (distinct from the handler's "creating",
    # which only means a create was requested) so a stuck task is observable.
    _write_json(client, status_key, {"status": "building", "customer": customer})
    # Any failure (infeasible design, or an unexpected error) must be recorded as
    # the WAN's status rather than crash the task and leave it stuck "creating".
    try:
        wan = _build_wan(client, customer)
    except Exception as exc:
        _write_json(client, status_key, {"status": "failed", "reason": str(exc)})
        return
    _write_json(client, f"customers/{customer}/wan.json", wan)
    _write_json(client, status_key, {"status": "ready"})
