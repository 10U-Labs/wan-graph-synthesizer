"use strict";

// Self-hosted Leaflet over OpenStreetMap. To run fully offline, point TILE_URL
// at a local tile server (e.g. tileserver-gl) instead of openstreetmap.org.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = "© OpenStreetMap contributors";

// The map shown on first load, before the operator picks a tenant.
const DEFAULT_MAP_ID = "joint";

// Vertex color and radius. CSP data centers are colored by kind; every other
// drawn vertex is colored by its tier role. Transit/unused carrier PoPs are
// not drawn.
const CSP_KIND = "CSP data center";
const CSP_STYLE = { color: "#ef6c00", radius: 5 };
const ROLE_STYLE = {
  core: { color: "#6a1b9a", radius: 8 },
  aggregation: { color: "#8bc34a", radius: 6 },
  access: { color: "#1565c0", radius: 4 },
};

// Each link tier matches its vertices' color and grows thicker up the tiers:
// access links are thinnest, aggregation links thicker, backbones thickest.
const EDGE_STYLE = {
  access: { color: ROLE_STYLE.access.color, weight: 1.5 },
  aggregation: { color: ROLE_STYLE.aggregation.color, weight: 3 },
  backbone: { color: ROLE_STYLE.core.color, weight: 4.5 },
};

const map = L.map("map").setView([39.5, -98.35], 4);
L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(map);

let drawn = [];

function styleFor(vertex) {
  if (vertex.kind === CSP_KIND) {
    return CSP_STYLE;
  }
  return ROLE_STYLE[vertex.tier_role] || null;
}

// Tier-role label prefixes, so every cored/aggregated vertex tooltip
// announces its role up front. Untiered vertices (CSP, transit) get no prefix.
const TIER_PREFIX = {
  core: "CORE",
  aggregation: "AGGR",
};

// Tooltip: the role-prefixed vertex name, its municipality/state beneath, then
// the tenant.
function vertexLabel(vertex) {
  const info = vertex.info || {};
  const located = info.municipality && info.state
    ? `<br>${info.municipality}, ${info.state}`
    : "";
  const prefix = TIER_PREFIX[vertex.tier_role];
  const name = prefix ? `${prefix} ${vertex.name}` : vertex.name;
  return `<strong>${name}</strong>${located}<br>Tenant: ${vertex.tenant}`;
}

function edgeLabel(source, target) {
  return `<strong>${source.name}</strong> ↔ <strong>${target.name}</strong>`;
}

function clear() {
  for (const layer of drawn) {
    map.removeLayer(layer);
  }
  drawn = [];
}

function add(layer) {
  layer.addTo(map);
  drawn.push(layer);
}

// Build a vertex's circle marker at the given coordinates, or null for
// transit/unused carrier PoPs (which are not drawn). Factored out so the
// primary marker and any antimeridian-wrapped duplicate share one style.
function vertexMarker(vertex, coords) {
  const style = styleFor(vertex);
  if (!style) {
    return null;
  }
  return L.circleMarker(coords, {
    radius: style.radius,
    color: style.color,
    fillColor: style.color,
    fillOpacity: 0.85,
    weight: 1,
  }).bindTooltip(vertexLabel(vertex));
}

// Draw every tiered vertex; skip transit/unused carrier PoPs. Returns the
// vertices indexed by id so edges can resolve their endpoints.
function drawVertices(vertices) {
  const byId = {};
  for (const vertex of vertices) {
    byId[vertex.id] = vertex;
    const marker = vertexMarker(vertex, vertex.coords);
    if (marker) {
      add(marker);
    }
  }
  return byId;
}

// Unwrap the target longitude relative to the source so a link spanning the
// antimeridian (e.g. a Pacific hop from the US west coast to the Marshall Islands)
// is drawn the short way west, not the long way east across the globe. When the
// target is unwrapped onto an adjacent world copy, `wrappedLon` reports the
// shifted longitude so the caller can duplicate the target's marker there.
function shortWayEnds(source, target) {
  const [, sourceLon] = source.coords;
  const [targetLat, targetLon] = target.coords;
  let lon = targetLon;
  if (lon - sourceLon > 180) {
    lon -= 360;
  } else if (lon - sourceLon < -180) {
    lon += 360;
  }
  return { ends: [source.coords, [targetLat, lon]], wrappedLon: lon === targetLon ? null : lon };
}

// Draw one set of edges in the given tier style, each with a hover tooltip.
// Records any target unwrapped onto an adjacent world copy in `wrapped` (keyed
// by id@lon so a vertex touched by many edges is duplicated only once).
function drawEdges(edges, byId, style, wrapped) {
  for (const edge of edges) {
    const source = byId[edge.source_id];
    const target = byId[edge.target_id];
    if (source && target) {
      const { ends, wrappedLon } = shortWayEnds(source, target);
      add(L.polyline(ends, {
        color: style.color,
        weight: style.weight,
        opacity: 0.8,
      }).bindTooltip(edgeLabel(source, target), { sticky: true }));
      if (wrappedLon !== null) {
        wrapped.set(`${target.id}@${wrappedLon}`, {
          vertex: target,
          coords: [target.coords[0], wrappedLon],
        });
      }
    }
  }
}

// Duplicate each antimeridian-wrapped endpoint's marker onto the world copy
// where its link lands, so a trans-Pacific connection is visually complete.
// Returns the duplicated coordinates so they can be framed by fitBounds.
function drawWrappedMarkers(wrapped) {
  const coords = [];
  for (const entry of wrapped.values()) {
    const marker = vertexMarker(entry.vertex, entry.coords);
    if (marker) {
      add(marker);
      coords.push(entry.coords);
    }
  }
  return coords;
}

// Split the routed core/aggregation paths by purpose for distinct styling.
function pathsByPurpose(pathUses, purpose) {
  return pathUses.filter((use) => use.purpose === purpose);
}

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} → ${response.status}`);
  }
  return response.json();
}

// Show the design's core and aggregation tallies in the top-right of the bar.
function showCounts(summary) {
  const counts = document.getElementById("counts");
  counts.textContent = `CORES ${summary.core_count} AGGR ${summary.aggregation_count}`;
}

async function render(mapId) {
  clear();
  const [vertices, edges, summary] = await Promise.all([
    getJSON(`/api/wan-maps/${mapId}/vertices`),
    getJSON(`/api/wan-maps/${mapId}/edges`),
    getJSON(`/api/wan-maps/${mapId}/summary`),
  ]);
  showCounts(summary);

  const byId = drawVertices(vertices);
  const wrapped = new Map();
  drawEdges(pathsByPurpose(edges.path_uses, "core_mesh"), byId, EDGE_STYLE.backbone, wrapped);
  drawEdges(
    pathsByPurpose(edges.path_uses, "aggregation_to_core"),
    byId, EDGE_STYLE.aggregation, wrapped,
  );
  drawEdges(edges.access_edges, byId, EDGE_STYLE.access, wrapped);
  const wrappedCoords = drawWrappedMarkers(wrapped);

  const points = vertices.map((vertex) => vertex.coords).concat(wrappedCoords);
  if (points.length) {
    map.fitBounds(points, { padding: [30, 30] });
  }
}

// Mark the chosen tenant link active and redraw its WAN map.
function select(link, mapId) {
  for (const other of document.querySelectorAll("#tenants a")) {
    other.classList.toggle("active", other === link);
  }
  return render(mapId);
}

async function init() {
  const tenants = document.getElementById("tenants");
  const wanMaps = await getJSON("/api/wan-maps");
  const entries = wanMaps.map((wanMap) => {
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = wanMap.label;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      select(link, wanMap.id);
    });
    tenants.appendChild(link);
    return { link, wanMap };
  });
  const start = entries.find((entry) => entry.wanMap.id === DEFAULT_MAP_ID) || entries[0];
  if (start) {
    await select(start.link, start.wanMap.id);
  }
}

init().catch((error) => {
  console.error(error);
});
