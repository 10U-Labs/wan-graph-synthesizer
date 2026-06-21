"""Seed the wan-graph-designer API from the git-authored data/ + etc/ inputs.

Carriers (PoPs + fiber) and CSPs (regions) are pushed as graphs; each customer's
installations, CSP-region selection, and design config are pushed as its inputs.
A write triggers the API's auto-create cascade (substrate merge + WAN creates).
The HTTPS PUT endpoint is the only write path; this client is one caller of it.

Usage: python scripts/push_inputs.py [api_base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from repo_utils import REPO_ROOT
from wan_designer.graph_collections import input_graph
from wan_designer.parsing import load_carrier_edges, load_vertices

DEFAULT_API = "https://api.10ulabs.com/wan-graph-designer"
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"
CSP_PROVIDERS = ("aws", "azure", "oci")


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


def _carrier_names() -> list[str]:
    """The carriers: every vertices file that also has a fiber-edge file."""
    return sorted(p.stem for p in (DATA / "edges").glob("*.csv"))


def push_carriers(api: str) -> None:
    """Push each carrier's PoPs and fiber.

    All carrier vertices are loaded together so ids are consistent and regional
    edges (which reference the main carrier's PoPs) resolve against the combined
    set -- the substrate is their union. Each carrier stores its own PoPs and the
    edges from its fiber file (shaped against the combined PoPs for names).
    """
    carriers = _carrier_names()
    all_pops = load_vertices([(c, DATA / "vertices" / f"{c}.csv") for c in carriers])
    by_tenant: dict[str, list[Any]] = {}
    for vertex in all_pops:
        by_tenant.setdefault(vertex.tenant, []).append(vertex)
    for carrier in carriers:
        own = by_tenant.get(carrier, [])
        edges = load_carrier_edges(DATA / "edges" / f"{carrier}.csv", all_pops)
        cid = _slug(carrier)
        print(f"carrier {cid}: {len(own)} pops, {len(edges)} edges")
        _put(api, f"carriers/{cid}/vertices", input_graph(own, {})["vertices"])
        _put(api, f"carriers/{cid}/edges", input_graph(all_pops, edges)["edges"])


def push_csps(api: str) -> None:
    """Push each cloud provider's regions (all its region files combined)."""
    for provider in CSP_PROVIDERS:
        files = sorted((DATA / "vertices").glob(f"{provider}_*.csv"))
        if not files:
            continue
        vertices = load_vertices([(provider.upper(), path) for path in files])
        print(f"csp {provider}: {len(vertices)} regions")
        _put(api, f"csps/{provider}/vertices", input_graph(vertices, {})["vertices"])


def _customer_inputs(config: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """Split a config's vertices into (installations, csp-regions) by tenant."""
    carriers = set(_carrier_names())
    installs: list[tuple[str, Path]] = []
    regions: list[tuple[str, Path]] = []
    for tenant, value in config.get("inputs", {}).get("vertices", {}).items():
        for raw in value if isinstance(value, list) else [value]:
            path = REPO_ROOT / raw
            if path.stem in carriers:
                continue
            target = regions if tenant.lower() in CSP_PROVIDERS else installs
            target.append((tenant, path))
    return (
        load_vertices(installs) if installs else [],
        load_vertices(regions) if regions else [],
    )


def push_customers(api: str) -> None:
    """Push each customer's installations, CSP regions, and design config."""
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        installs, regions = _customer_inputs(config)
        design = {key: value for key, value in config.items() if key != "inputs"}
        cid = _slug(path.stem)
        print(f"customer {cid}: {len(installs)} installations, {len(regions)} regions")
        _put(api, f"customers/{cid}/installations", input_graph(installs, {}))
        _put(api, f"customers/{cid}/csp-regions", input_graph(regions, {}))
        _put(api, f"customers/{cid}/config", design)


def main() -> None:
    """Seed carriers, CSPs, then customers (whose writes cascade to WAN builds)."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    push_csps(api)
    push_customers(api)


if __name__ == "__main__":
    main()
