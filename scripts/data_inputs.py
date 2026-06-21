"""Read the git-authored CSV inputs into the graph data model.

The inputs script (:mod:`push_inputs`) turns the raw per-tenant vertex CSVs, the
carrier fiber-edge CSVs, and the off-net candidate CSV into :class:`wan_graph.model`
objects, which it then serializes to JSON for the API. This module owns that
CSV-reading step; the optimizer endpoint never parses raw files -- it consumes the
JSON these readers feed.
"""

from __future__ import annotations

import csv
from pathlib import Path

from wan_graph.model import (
    PhysicalEdge,
    Vertex,
    VertexInfo,
    edge_key,
    haversine_miles,
    slugify,
)

OFF_NET_TENANT = "Off-net"
OFF_NET_KIND = "Off-net site"


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
                            justified_aggregation=(
                                row.get("Justified as an aggregation point", "").strip().lower()
                                == "yes"
                            ),
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
