"""Seed the wan-graph-synthesizer API from the git-authored data/ + etc/ inputs.

A plain reader-and-sender: read each cleaned CSV into simple rows (city, state,
latitude, longitude, plus a name where the source has one) and PUT them to the matching
endpoint. What each place *is* comes from the endpoint it is sent to, so nothing is
classified or shaped here; carrier connections (``A_/Z_`` city+state) are forwarded as
they stand and resolved server-side. Carriers push their points and connections;
providers push their regions; each tenant pushes its sites, provider-region selection,
off-net candidates, and per-concern config resources. The tenant configs in ``etc/`` are
the roster, so a tenant the API still lists once they have all been pushed is one git no
longer declares and is deleted. Writes only store inputs -- they trigger
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
from typing import Any, cast

import yaml

from repo_utils import REPO_ROOT

DEFAULT_API = "https://api.10ulabs.com/wan-graph-synthesizer"
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"


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


def _send(api: str, path: str, method: str, body: bytes | None) -> bytes:
    """Send a JSON request to the API and return its body, raising on a non-2xx response."""
    request = urllib.request.Request(
        f"{api}/{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"  {method} /{path} -> {response.status}", flush=True)
        return cast("bytes", response.read())


def _put(api: str, path: str, body: Any) -> None:
    """PUT a JSON body to an API collection, raising on a non-2xx response."""
    _send(api, path, "PUT", json.dumps(body).encode())


def _post(api: str, path: str) -> None:
    """POST to a build operation (no body), raising on a non-2xx response."""
    _send(api, path, "POST", b"")


def _get(api: str, path: str) -> Any:
    """GET a JSON document from the API, raising on a non-2xx response."""
    return json.loads(_send(api, path, "GET", None))


def _delete(api: str, path: str) -> None:
    """DELETE a resource from the API, raising on a non-2xx response."""
    _send(api, path, "DELETE", None)


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
        print(f"carrier {cid}: {len(vertices)} points, {len(edges)} connections", flush=True)
        _put(api, f"carriers/{cid}/vertices", vertices)
        _put(api, f"carriers/{cid}/edges", edges)


def push_providers(api: str) -> None:
    """Push the provider regions (a single combined vertices file)."""
    regions = _rows(DATA / "vertices" / "providers" / "providers.csv")
    print(f"providers: {len(regions)} regions", flush=True)
    _put(api, "providers/vertices", regions)


def _data_center_providers() -> list[str]:
    """The colocation providers: every facilities file under data-centers/."""
    return sorted(p.stem for p in (DATA / "vertices" / "data-centers").glob("*.csv"))


def push_data_centers(api: str) -> None:
    """Push each colocation provider's facilities as simple geographic rows."""
    for provider in _data_center_providers():
        pid = _slug(provider)
        facilities = _rows(DATA / "vertices" / "data-centers" / f"{provider}.csv")
        print(f"data-center {pid}: {len(facilities)} facilities", flush=True)
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
        backbone = config["backbone"]
        forced = backbone.get("forced", {})
        prohibited = backbone.get("prohibited", {})
        locations = _mapping_rows(inputs.get("locations", {}))
        regions = _mapping_rows(inputs.get("providers", {}))
        off_net_path = inputs.get("off_net")
        off_net = _rows(REPO_ROOT / off_net_path) if off_net_path else []
        print(f"tenant {tid}: {len(locations)} sites, {len(regions)} regions, "
              f"{len(off_net)} off-net", flush=True)
        _put(api, f"tenants/{tid}/locations", locations)
        _put(api, f"tenants/{tid}/provider-regions", regions)
        _put(api, f"tenants/{tid}/off-net", off_net)
        _put(api, f"tenants/{tid}/forced-backbone-nodes", forced.get("nodes", []))
        _put(api, f"tenants/{tid}/forced-connections", forced.get("connections", []))
        _put(api, f"tenants/{tid}/prohibited-backbone-nodes", prohibited.get("nodes", []))
        _put(api, f"tenants/{tid}/prohibited-connections", prohibited.get("connections", []))
        _put(api, f"tenants/{tid}/backbone-node-count", backbone.get("node_count", {}))
        _put(api, f"tenants/{tid}/backbone-mesh-degree",
             _degree_doc(backbone["mesh_degree"]))
        _put(api, f"tenants/{tid}/access-homing-degree",
             _degree_doc(config["access"]["homing_degree"]))
        _put(api, f"tenants/{tid}/backbone-placement",
             {"restrict": backbone["restrict_to_data_centers"]})
        _put(api, f"tenants/{tid}/convergence-promotion",
             {"promote": backbone["promote_high_degree_convergences"]})
        # The stored document keeps the unshortened key: the config drops the prefix its
        # block now supplies, but the synthesizer reads the target under the long name.
        _put(api, f"tenants/{tid}/knobs",
             {"backbone_coverage_target_miles": backbone["coverage_target_miles"]})
        _put(api, f"tenants/{tid}/settings", config.get("settings", {}))
        _put(api, f"tenants/{tid}/label", {"label": config.get("label", "")})
    return tenant_ids


def prune_tenants(api: str, tenants: list[str]) -> None:
    """Delete every stored tenant that ``etc/`` no longer declares.

    ``etc/`` is the roster: a tenant exists because a config file names it, so one the
    API still lists after the push is a tenant git has dropped, and its stored inputs
    and WAN go with it.
    """
    for entry in _get(api, "tenants"):
        tenant = entry["id"]
        if tenant in tenants:
            continue
        print(f"tenant {tenant}: deleting (no config in etc/)", flush=True)
        _delete(api, f"tenants/{tenant}")


def build_substrate(api: str) -> None:
    """Rebuild the shared carrier substrate from the pushed carriers."""
    print("merge: rebuilding substrate", flush=True)
    _post(api, "carriers/merge")


def build_data_centers(api: str) -> None:
    """Rebuild the data-center union from the pushed providers."""
    print("data-centers merge: rebuilding union", flush=True)
    _post(api, "data-centers/merge")


def build_tenants(api: str, tenants: list[str]) -> None:
    """Trigger one WAN build per tenant (the only build trigger)."""
    for tid in tenants:
        print(f"tenant {tid}: building WAN", flush=True)
        _post(api, f"tenants/{tid}/wan")


def main() -> None:
    """Seed inputs, prune dropped tenants, then rebuild the substrate and each WAN."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    build_substrate(api)
    push_providers(api)
    push_data_centers(api)
    build_data_centers(api)
    tenants = push_tenants(api)
    prune_tenants(api, tenants)
    build_tenants(api, tenants)


if __name__ == "__main__":  # pragma: no cover
    main()
