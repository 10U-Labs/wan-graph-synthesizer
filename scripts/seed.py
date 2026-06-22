"""Seed the wan-graph-designer API from the git-authored data/ + etc/ inputs.

One script, three steps: read the raw per-tenant vertex CSVs, the carrier fiber-edge
CSVs, and the off-net candidate CSV into :class:`wan_graph.model` objects (extract);
shape them as JSON via :func:`wan_graph.codec.input_graph` (transform); and PUT them to
the API (load). Carriers (PoPs + fiber) and CSPs (regions) are pushed as graphs; each
customer's locations, CSP-region selection, and per-concern config resources are pushed
as its inputs. A write triggers the API's auto-create cascade (substrate merge + WAN
creates). The HTTPS PUT endpoint is the only write path; this client is one caller of it.

Usage: python scripts/seed.py [api_base_url]
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from repo_utils import REPO_ROOT
from wan_graph.codec import input_graph
from wan_graph.model import PhysicalEdge, Vertex, VertexInfo, edge_key, haversine_miles

DEFAULT_API = "https://api.10ulabs.com/wan-graph-designer"
DATA = REPO_ROOT / "data"
ETC = REPO_ROOT / "etc"
CSP_PROVIDERS = ("aws", "azure", "oci")
OFF_NET_TENANT = "Off-net"
OFF_NET_KIND = "Off-net site"


def slugify(value: str) -> str:
    """Normalize a string into a lowercase underscore-separated id slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "vertex"


# --- extract: read the git-authored CSV inputs into the graph data model ---


def load_vertices(vertex_files: list[tuple[str, Path]]) -> list[Vertex]:
    """Load vertices from one CSV per tenant.

    Each ``(tenant, path)`` pair names a CSV whose rows are
    ``name,latitude,longitude,kind,shown_in_map,description,municipality,state``
    -- the ``tenant`` is supplied by the caller because the CSVs carry no tenant
    column; ``municipality`` and ``state`` are the serving city and 2-letter state
    for display. ``kind``
    classifies the vertex (``PoP``/``ROADM`` carrier PoPs versus access and
    cloud-region vertices). Ids are slugged from the name and de-duplicated
    across all files, so the same name may appear under more than one tenant.
    """
    vertices: list[Vertex] = []
    used_ids: set[str] = set()
    for tenant, path in vertex_files:
        if not path.exists():
            raise ValueError(f"Vertex file does not exist: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = row["name"].strip()
                base_id = slugify(name)
                vertex_id = base_id
                suffix = 2
                while vertex_id in used_ids:
                    vertex_id = f"{base_id}_{suffix}"
                    suffix += 1
                used_ids.add(vertex_id)
                vertices.append(
                    Vertex(
                        id=vertex_id,
                        name=name,
                        tenant=tenant,
                        kind=row["kind"].strip(),
                        coords=(float(row["latitude"]), float(row["longitude"])),
                        info=VertexInfo(
                            description=row.get("description", "").strip(),
                            municipality=row.get("municipality", "").strip(),
                            state=row.get("state", "").strip(),
                        ),
                        shown_in_map=row.get("shown_in_map", "").strip() != "Not shown in map",
                    )
                )
    return vertices


def load_carrier_edges(
    path: Path, carrier_pops: list[Vertex]
) -> dict[tuple[str, str], PhysicalEdge]:
    """Load a physical Carrier edge graph from a mapbook-derived edge CSV."""
    if not path.exists():
        raise ValueError(f"Carrier edge file does not exist: {path}")

    by_name = {pop.name.lower(): pop for pop in carrier_pops}
    edges: dict[tuple[str, str], PhysicalEdge] = {}

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_name = row["source"].strip().lower()
            target_name = row["target"].strip().lower()
            if source_name not in by_name:
                raise ValueError(f"Edge file references unknown source PoP: {row['source']}")
            if target_name not in by_name:
                raise ValueError(f"Edge file references unknown target PoP: {row['target']}")

            source = by_name[source_name]
            target = by_name[target_name]
            key = edge_key(source.id, target.id)
            if row.get("distance_miles"):
                distance = float(row["distance_miles"])
            else:
                distance = haversine_miles(source, target)
            edges[key] = PhysicalEdge(
                source=key[0],
                target=key[1],
                distance_miles=distance,
                source_page=row.get("source_page", ""),
                note=row.get("note", ""),
            )

    return edges


def load_off_net_sites(path: Path) -> list[Vertex]:
    """Load off-net candidate sites from a ``name,latitude,longitude`` CSV.

    These are lookup records used only to synthesize twins for forced seats; they are
    never merged into the main vertex pool and so generate no demand.
    """
    if not path.exists():
        raise ValueError(f"Off-net site file does not exist: {path}")
    sites: list[Vertex] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["name"].strip()
            sites.append(
                Vertex(
                    id=slugify(name),
                    name=name,
                    tenant=OFF_NET_TENANT,
                    kind=OFF_NET_KIND,
                    coords=(float(row["latitude"]), float(row["longitude"])),
                )
            )
    return sites


# --- load: shape the model objects as JSON and PUT them to the API ---


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
    all_pops = load_vertices(
        [(c, DATA / "vertices" / "carriers" / f"{c}.csv") for c in carriers]
    )
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
        files = sorted((DATA / "vertices" / "csps" / provider).glob("*.csv"))
        if not files:
            continue
        vertices = load_vertices([(provider.upper(), path) for path in files])
        print(f"csp {provider}: {len(vertices)} regions")
        _put(api, f"csps/{provider}/vertices", input_graph(vertices, {})["vertices"])


def _tenant_vertices(mapping: dict[str, Any]) -> list[Any]:
    """Load a ``{tenant: csv-or-list}`` mapping into a flat list of vertices."""
    files: list[tuple[str, Path]] = []
    for tenant, value in mapping.items():
        for raw in value if isinstance(value, list) else [value]:
            files.append((tenant, REPO_ROOT / raw))
    return load_vertices(files) if files else []


def _degree_doc(value: Any) -> dict[str, Any]:
    """Wrap a required redundancy degree as its ``{"degree": int}`` document."""
    return {"degree": value}


def push_customers(api: str) -> None:
    """Push each customer's inputs: locations, CSP regions, off-net, and every config resource."""
    for path in sorted(ETC.glob("*.yml")):
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cid = _slug(path.stem)
        inputs = config.get("inputs", {})
        locations = _tenant_vertices(inputs.get("locations", {}))
        regions = _tenant_vertices(inputs.get("csps", {}))
        off_net_path = inputs.get("off_net")
        off_net = load_off_net_sites(REPO_ROOT / off_net_path) if off_net_path else []
        print(f"customer {cid}: {len(locations)} locations, {len(regions)} regions, "
              f"{len(off_net)} off-net")
        _put(api, f"customers/{cid}/locations", input_graph(locations, {}))
        _put(api, f"customers/{cid}/csp-regions", input_graph(regions, {}))
        _put(api, f"customers/{cid}/off-net", input_graph(off_net, {}))
        _put(api, f"customers/{cid}/forced-core-nodes", config.get("forced_core_nodes", []))
        _put(api, f"customers/{cid}/forced-aggregation-points",
             config.get("forced_aggregation_points", []))
        _put(api, f"customers/{cid}/forced-connections", config.get("forced_connections", []))
        _put(api, f"customers/{cid}/prohibited-core-nodes",
             config.get("prohibited_core_nodes", []))
        _put(api, f"customers/{cid}/prohibited-aggregation-points",
             config.get("prohibited_aggregation_points", []))
        _put(api, f"customers/{cid}/prohibited-connections",
             config.get("prohibited_connections", []))
        _put(api, f"customers/{cid}/core-node-count", config.get("core_node_count", {}))
        _put(api, f"customers/{cid}/core-mesh-degree", _degree_doc(config["core_mesh_degree"]))
        _put(api, f"customers/{cid}/aggregation-homing-degree",
             _degree_doc(config["aggregation_homing_degree"]))
        _put(api, f"customers/{cid}/access-homing-degree",
             _degree_doc(config["access_homing_degree"]))
        _put(api, f"customers/{cid}/knobs", config.get("knobs", {}))
        _put(api, f"customers/{cid}/label", {"label": config.get("label", "")})


def main() -> None:
    """Seed carriers, CSPs, then customers (whose writes cascade to WAN builds)."""
    api = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    push_carriers(api)
    push_csps(api)
    push_customers(api)


if __name__ == "__main__":  # pragma: no cover
    main()
