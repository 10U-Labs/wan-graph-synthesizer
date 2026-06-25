"""Seed the wan-graph-synthesizer API from the git-authored data/ + etc/ inputs.

A plain reader-and-sender: read each cleaned CSV into simple rows (city, state,
latitude, longitude, plus a name where the source has one) and PUT them to the matching
endpoint. What each place *is* comes from the endpoint it is sent to, so nothing is
classified or shaped here; carrier connections (``A_/Z_`` city+state) are forwarded as
they stand and resolved server-side. Carriers push their points and connections; CSPs
push their regions; each tenant pushes its sites, CSP-region selection, off-net
candidates, and per-concern config resources. Writes only store inputs -- they trigger
nothing -- so the seed then explicitly rebuilds the shared substrate
(``POST carriers/merge``) and each tenant's WAN (``POST tenants/{t}/wan``).

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


def _send(api: str, path: str, method: str, body: bytes) -> None:
    """Send a JSON request to the API, raising on a non-2xx response."""
    request = urllib.request.Request(
        f"{api}/{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"  {method} /{path} -> {response.status}")


def _put(api: str, path: str, body: Any) -> None:
    """PUT a JSON body to an API collection, raising on a non-2xx response."""
    _send(api, path, "PUT", json.dumps(body).encode())


def _post(api: str, path: str) -> None:
    """POST to a build operation (no body), raising on a non-2xx response."""
    _send(api, path, "POST", b"")


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


def _data_center_providers() -> list[str]:
    """The colocation providers: every facilities file under data-centers/."""
    return sorted(p.stem for p in (DATA / "vertices" / "data-centers").glob("*.csv"))


def push_data_centers(api: str) -> None:
    """Push each colocation provider's facilities as simple geographic rows."""
    for provider in _data_center_providers():
        pid = _slug(provider)
        facilities = _rows(DATA / "vertices" / "data-centers" / f"{provider}.csv")
        print(f"data-center {pid}: {len(facilities)} facilities")
        _put(api, f"data-centers/{pid}/vertices", facilities)


def push_tenants(api: str) -> list[str]:
    """Push each tenant's inputs and return the tenant ids (for the build step)."""
    tenant_ids: list[str] = []
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not config:
            continue
        tid = _slug(path.stem)
        tenant_ids.append(tid)
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
        _put(api, f"tenants/{tid}/forced-backbone-nodes",
             config.get("forced_backbone_nodes", []))
        _put(api, f"tenants/{tid}/forced-connections", config.get("forced_connections", []))
        _put(api, f"tenants/{tid}/prohibited-backbone-nodes",
             config.get("prohibited_backbone_nodes", []))
        _put(api, f"tenants/{tid}/prohibited-connections",
             config.get("prohibited_connections", []))
        _put(api, f"tenants/{tid}/backbone-node-count", config.get("backbone_node_count", {}))
        _put(api, f"tenants/{tid}/backbone-mesh-degree",
             _degree_doc(config["backbone_mesh_degree"]))
        _put(api, f"tenants/{tid}/access-homing-degree",
             _degree_doc(config["access_homing_degree"]))
        _put(api, f"tenants/{tid}/knobs", config.get("knobs", {}))
        _put(api, f"tenants/{tid}/label", {"label": config.get("label", "")})
    return tenant_ids


def build_substrate(api: str) -> None:
    """Rebuild the shared carrier substrate from the pushed carriers."""
    print("merge: rebuilding substrate")
    _post(api, "carriers/merge")


def build_data_centers(api: str) -> None:
    """Rebuild the data-center union from the pushed providers."""
    print("data-centers merge: rebuilding union")
    _post(api, "data-centers/merge")


def build_tenants(api: str, tenants: list[str]) -> None:
    """Trigger one WAN build per tenant (the only build trigger)."""
    for tid in tenants:
        print(f"tenant {tid}: building WAN")
        _post(api, f"tenants/{tid}/wan")


def main() -> None:
    """Seed inputs, then explicitly rebuild the substrate and each tenant's WAN."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    build_substrate(api)
    push_csps(api)
    push_data_centers(api)
    build_data_centers(api)
    tenants = push_tenants(api)
    build_tenants(api, tenants)


if __name__ == "__main__":  # pragma: no cover
    main()
