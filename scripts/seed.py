"""Seed the wan-graph-synthesizer API from the git-authored data/ + etc/ inputs.

A plain reader-and-sender: read each cleaned CSV into simple rows (city, state,
latitude, longitude, plus a name where the source has one) and PUT them to the matching
endpoint. What each place *is* comes from the endpoint it is sent to, so nothing is
classified or shaped here; carrier connections (``A_/Z_`` city+state) are forwarded as
they stand and resolved server-side. Carriers push their points and connections; CSPs
push their regions; each tenant pushes its sites, CSP-region selection, off-net
candidates, and per-concern config resources. A write triggers the API's auto-create
cascade (substrate merge + WAN builds). The HTTPS PUT endpoint is the only write path.

Usage: python scripts/seed.py [api_base_url]
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from repo_utils import REPO_ROOT

DEFAULT_API = "https://api.10ulabs.com/wan-graph-synthesizer"
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"
CSP_PROVIDERS = ("aws", "azure", "oci")


def _rows(path: Path) -> list[dict[str, Any]]:
    """Read a cleaned CSV into simple rows: lowercased keys, numeric lat/lon."""
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows: list[dict[str, Any]] = []
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = {key.lower(): value.strip() for key, value in raw.items()}
            if "latitude" in row:
                row["latitude"] = float(row["latitude"])
                row["longitude"] = float(row["longitude"])
            rows.append(row)
        return rows


def _mapping_rows(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a ``{label: csv-or-list}`` inputs mapping into one list of rows.

    The labels group the source files but are not the owner -- the tenant is -- so they
    are dropped and every file's rows are concatenated.
    """
    rows: list[dict[str, Any]] = []
    for value in mapping.values():
        for raw in value if isinstance(value, list) else [value]:
            rows.extend(_rows(REPO_ROOT / raw))
    return rows


def _slug(stem: str) -> str:
    """A url-safe resource id from a file stem (underscores become hyphens)."""
    return stem.replace("_", "-")


def _put(api: str, path: str, body: Any) -> None:
    """PUT a JSON body to an API collection, raising on a non-2xx response."""
    request = urllib.request.Request(
        f"{api}/{path}",
        data=json.dumps(body).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"  PUT /{path} -> {response.status}")


def _degree_doc(value: Any) -> dict[str, Any]:
    """Wrap a required redundancy degree as its ``{"degree": int}`` document."""
    return {"degree": value}


def _carrier_names() -> list[str]:
    """The carriers: every points file that also has a connections file."""
    return sorted(p.stem for p in (DATA / "edges").glob("*.csv"))


def push_carriers(api: str) -> None:
    """Push each carrier's points and connections as simple rows."""
    for carrier in _carrier_names():
        cid = _slug(carrier)
        vertices = _rows(DATA / "vertices" / "carriers" / f"{carrier}.csv")
        edges = _rows(DATA / "edges" / f"{carrier}.csv")
        print(f"carrier {cid}: {len(vertices)} points, {len(edges)} connections")
        _put(api, f"carriers/{cid}/vertices", vertices)
        _put(api, f"carriers/{cid}/edges", edges)


def push_csps(api: str) -> None:
    """Push each cloud provider's regions (all its region files combined)."""
    for provider in CSP_PROVIDERS:
        files = sorted((DATA / "vertices" / "csps" / provider).glob("*.csv"))
        if not files:
            continue
        regions = [row for path in files for row in _rows(path)]
        print(f"csp {provider}: {len(regions)} regions")
        _put(api, f"csps/{provider}/vertices", regions)


def push_tenants(api: str) -> None:
    """Push each tenant's inputs: sites, CSP regions, off-net, and every config resource."""
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not config:
            continue
        tid = _slug(path.stem)
        inputs = config.get("inputs", {})
        locations = _mapping_rows(inputs.get("locations", {}))
        regions = _mapping_rows(inputs.get("csps", {}))
        off_net_path = inputs.get("off_net")
        off_net = _rows(REPO_ROOT / off_net_path) if off_net_path else []
        print(f"tenant {tid}: {len(locations)} sites, {len(regions)} regions, "
              f"{len(off_net)} off-net")
        _put(api, f"tenants/{tid}/locations", locations)
        _put(api, f"tenants/{tid}/csp-regions", regions)
        _put(api, f"tenants/{tid}/off-net", off_net)
        _put(api, f"tenants/{tid}/forced-core-nodes", config.get("forced_core_nodes", []))
        _put(api, f"tenants/{tid}/forced-aggregation-points",
             config.get("forced_aggregation_points", []))
        _put(api, f"tenants/{tid}/forced-connections", config.get("forced_connections", []))
        _put(api, f"tenants/{tid}/prohibited-core-nodes",
             config.get("prohibited_core_nodes", []))
        _put(api, f"tenants/{tid}/prohibited-aggregation-points",
             config.get("prohibited_aggregation_points", []))
        _put(api, f"tenants/{tid}/prohibited-connections",
             config.get("prohibited_connections", []))
        _put(api, f"tenants/{tid}/core-node-count", config.get("core_node_count", {}))
        _put(api, f"tenants/{tid}/core-mesh-degree", _degree_doc(config["core_mesh_degree"]))
        _put(api, f"tenants/{tid}/aggregation-homing-degree",
             _degree_doc(config["aggregation_homing_degree"]))
        _put(api, f"tenants/{tid}/access-homing-degree",
             _degree_doc(config["access_homing_degree"]))
        _put(api, f"tenants/{tid}/knobs", config.get("knobs", {}))
        _put(api, f"tenants/{tid}/label", {"label": config.get("label", "")})


def main() -> None:
    """Seed carriers, CSPs, then tenants (whose writes cascade to WAN builds)."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    push_csps(api)
    push_tenants(api)


if __name__ == "__main__":  # pragma: no cover
    main()
