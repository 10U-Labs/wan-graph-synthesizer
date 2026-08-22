from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import yaml

from repo_utils import REPO_ROOT

DEFAULT_API = "https://api.10ulabs.com/wan-synthesizer"
RETRY_PAUSE_SECONDS = 1.0
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"


def _rows(path: Path) -> list[dict[str, Any]]:
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
    rows: list[dict[str, Any]] = []
    for value in mapping.values():
        for raw in value if isinstance(value, list) else [value]:
            rows.extend(_rows(REPO_ROOT / raw))
    return rows


def _city_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["municipality"]).casefold(), str(row["state"]).casefold()


def _carrier_cities() -> set[tuple[str, str]]:
    return {
        _city_key(row)
        for carrier in _carrier_names()
        for row in _rows(DATA / "pops" / f"{carrier}.csv")
    }


def _off_net_rows(path: str) -> list[dict[str, Any]]:
    rows = _rows(REPO_ROOT / path)
    carriers = _carrier_cities()
    on_net = sorted(
        f"{row['municipality']}, {row['state']}"
        for row in rows if _city_key(row) in carriers
    )
    if on_net:
        raise ValueError(
            f"off-net file {path} names cities a carrier already serves: "
            f"{'; '.join(on_net)}")
    return rows


def _slug(stem: str) -> str:
    return stem.replace("_", "-")


def _is_dropped_connection(failure: OSError) -> bool:
    if isinstance(failure, urllib.error.HTTPError):
        return False
    if isinstance(failure, urllib.error.URLError):
        return isinstance(failure.reason, ConnectionResetError)
    return isinstance(failure, ConnectionResetError)


def _send_once(request: urllib.request.Request, method: str, path: str) -> bytes:
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"  {method} /{path} -> {response.status}", flush=True)
        return cast("bytes", response.read())


def _send(api: str, path: str, method: str, body: bytes | None) -> bytes:
    request = urllib.request.Request(
        f"{api}/{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        return _send_once(request, method, path)
    except OSError as failure:
        if not _is_dropped_connection(failure):
            raise
    print(f"  {method} /{path} -> connection reset, trying once more", flush=True)
    time.sleep(RETRY_PAUSE_SECONDS)
    return _send_once(request, method, path)


def _put(api: str, path: str, body: Any) -> None:
    _send(api, path, "PUT", json.dumps(body).encode())


def _post(api: str, path: str) -> None:
    _send(api, path, "POST", b"")


def _post_json(api: str, path: str) -> Any:
    return json.loads(_send(api, path, "POST", b""))


def _get(api: str, path: str) -> Any:
    return json.loads(_send(api, path, "GET", None))


def _delete(api: str, path: str) -> None:
    _send(api, path, "DELETE", None)


def _degree_doc(value: Any) -> dict[str, Any]:
    return {"degree": value}


def _carrier_names() -> list[str]:
    return sorted(p.stem for p in (DATA / "fiber_segments").glob("*.csv"))


def push_carriers(api: str) -> None:
    for carrier in _carrier_names():
        cid = _slug(carrier)
        pops = _rows(DATA / "pops" / f"{carrier}.csv")
        fiber_segments = _rows(DATA / "fiber_segments" / f"{carrier}.csv")
        print(f"carrier {cid}: {len(pops)} points, "
              f"{len(fiber_segments)} fiber segments", flush=True)
        _put(api, f"carriers/{cid}/pops", pops)
        _put(api, f"carriers/{cid}/fiber-segments", fiber_segments)


def push_providers(api: str) -> None:
    regions = _rows(DATA / "providers" / "providers.csv")
    print(f"providers: {len(regions)} regions", flush=True)
    _put(api, "providers/regions", regions)


def push_tenants(api: str) -> list[str]:
    tenant_ids: list[str] = []
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not config:
            continue
        tid = _slug(path.stem)
        tenant_ids.append(tid)
        inputs = config.get("inputs", {})
        access = config["access"]
        backbone = config["backbone"]
        forced = backbone.get("forced", {})
        prohibited = backbone.get("prohibited", {})
        homes = access.get("forced", {}).get("homes", [])
        locations = _mapping_rows(inputs.get("locations", {}))
        regions = _rows(REPO_ROOT / inputs["providers"]) if inputs.get("providers") else []
        off_net_file = inputs.get("forced")
        off_net = _off_net_rows(off_net_file) if off_net_file else []
        print(f"tenant {tid}: {len(locations)} sites, {len(regions)} regions, "
              f"{len(off_net)} off-net", flush=True)
        _put(api, f"tenants/{tid}/locations", locations)
        _put(api, f"tenants/{tid}/provider-regions", regions)
        _put(api, f"tenants/{tid}/off-net", off_net)
        _put(api, f"tenants/{tid}/forced-backbone-nodes", forced.get("nodes", []))
        _put(api, f"tenants/{tid}/forced-paths", forced.get("paths", []))
        _put(api, f"tenants/{tid}/forced-homes", homes)
        _put(api, f"tenants/{tid}/prohibited-backbone-nodes", prohibited.get("nodes", []))
        _put(api, f"tenants/{tid}/prohibited-paths", prohibited.get("paths", []))
        _put(api, f"tenants/{tid}/degree-exempt-backbone-nodes",
             backbone.get("degree_exempt", []))
        _put(api, f"tenants/{tid}/backbone-node-count", backbone.get("node_count", {}))
        _put(api, f"tenants/{tid}/backbone-number-of-diverse-paths",
             _degree_doc(backbone["number_of_diverse_paths"]))
        _put(api, f"tenants/{tid}/access-homing-degree",
             _degree_doc(access["homing_degree"]))
        _put(api, f"tenants/{tid}/convergence-promotion",
             {"promote": backbone["promote_high_degree_convergences"]})
        _put(api, f"tenants/{tid}/knobs", {
            "backbone_coverage_target_miles": backbone["coverage_target_miles"],
            "backbone_max_backup_path_multiple": backbone["max_backup_path_multiple"],
        })
        _put(api, f"tenants/{tid}/settings", config.get("settings", {}))
        _put(api, f"tenants/{tid}/label", {"label": config.get("label", "")})
    return tenant_ids


def prune_tenants(api: str, tenants: list[str]) -> None:
    for entry in _get(api, "tenants"):
        tenant = entry["id"]
        if tenant in tenants:
            continue
        print(f"tenant {tenant}: deleting (no config in etc/)", flush=True)
        _delete(api, f"tenants/{tenant}")


def prune_store(api: str) -> None:
    print("store: pruning collections nothing writes any more", flush=True)
    answer = _post_json(api, "store/prune")
    deleted = answer.get("deleted", []) if isinstance(answer, dict) else []
    for key in deleted:
        print(f"  deleted {key}", flush=True)


def build_merged_carriers(api: str) -> None:
    print("merge: rebuilding the merged carriers", flush=True)
    _post(api, "carriers/merge")


def build_tenants(api: str, tenants: list[str]) -> None:
    for tid in tenants:
        print(f"tenant {tid}: building WAN", flush=True)
        _post(api, f"tenants/{tid}/wan")


def main() -> None:
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    build_merged_carriers(api)
    push_providers(api)
    tenants = push_tenants(api)
    prune_tenants(api, tenants)
    prune_store(api)
    build_tenants(api, tenants)

