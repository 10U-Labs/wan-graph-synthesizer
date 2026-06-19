"use strict";

// Self-hosted Leaflet over OpenStreetMap. To run fully offline, point TILE_URL
// at a local tile server (e.g. tileserver-gl) instead of openstreetmap.org.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = "© OpenStreetMap contributors";

// The map shown on first load, before the operator picks a tenant.
const DEFAULT_MAP_ID = "military_installations";

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

// The CONUS center the map opens on; also the meridian every vertex is anchored
// to, so far-side-of-the-antimeridian sites render on the world copy nearest it.
const VIEW_CENTER = [39.5, -98.35];

const map = L.map("map").setView(VIEW_CENTER, 4);
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

// The bare city: the vertex name stripped of any trailing ", ST" state and any
// leading role prefix (co-located twins are named "AGGR <core>" server-side), so
// the role-prefixed name reads "CORE Los Angeles", never "CORE Los Angeles, CA"
// or a doubled "AGGR AGGR Los Angeles".
function cityName(vertex) {
  return vertex.name.replace(/^(?:CORE|AGGR)\s+/, "").replace(/,\s*[A-Z]{2}$/, "");
}

// Role-prefixed display name, e.g. "CORE Los Angeles". Untiered vertices (access,
// CSP, transit) keep their full name unchanged.
function displayName(vertex) {
  const prefix = TIER_PREFIX[vertex.tier_role];
  return prefix ? `${prefix} ${cityName(vertex)}` : vertex.name;
}

// Tooltip: the role-prefixed display name, its municipality/state beneath, then
// the tenant.
function vertexLabel(vertex) {
  const info = vertex.info || {};
  const located = info.municipality && info.state
    ? `<br>${info.municipality}, ${info.state}`
    : "";
  return `<strong>${displayName(vertex)}</strong>${located}<br>Tenant: ${vertex.tenant}`;
}

function edgeLabel(source, target) {
  return `<strong>${displayName(source)}</strong> ↔ <strong>${displayName(target)}</strong>`;
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
// transit/unused carrier PoPs (which are not drawn).
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

// Shift a longitude onto the copy of the world nearest the map's center
// meridian, so a far-side-of-the-antimeridian site (e.g. the Marshall Islands
// at 167.7°E) renders on the copy just west of CONUS, not off the east edge.
function nearLon(lon) {
  let shifted = lon;
  while (shifted - VIEW_CENTER[1] > 180) {
    shifted -= 360;
  }
  while (shifted - VIEW_CENTER[1] < -180) {
    shifted += 360;
  }
  return shifted;
}

// A vertex's drawing coordinates, with its longitude anchored to the CONUS copy.
function displayCoords(vertex) {
  return [vertex.coords[0], nearLon(vertex.coords[1])];
}

// Index the vertices by id so edges can resolve their endpoints. Drawing is
// deferred to drawVertices so markers land on top of the edges.
function indexById(vertices) {
  const byId = {};
  for (const vertex of vertices) {
    byId[vertex.id] = vertex;
  }
  return byId;
}

// Draw every tiered vertex at its CONUS-anchored position; skip transit/unused
// carrier PoPs. Returns the drawn coordinates so fitBounds can frame them.
function drawVertices(vertices) {
  const coords = [];
  for (const vertex of vertices) {
    const at = displayCoords(vertex);
    const marker = vertexMarker(vertex, at);
    if (marker) {
      add(marker);
      coords.push(at);
    }
  }
  return coords;
}

// Draw one set of edges in the given tier style, each with a hover tooltip.
// Endpoints use CONUS-anchored coordinates, so a trans-Pacific link is drawn the
// short way to the world copy beside CONUS rather than the long way east.
function drawEdges(edges, byId, style) {
  for (const edge of edges) {
    const source = byId[edge.source_id];
    const target = byId[edge.target_id];
    if (source && target) {
      add(L.polyline([displayCoords(source), displayCoords(target)], {
        color: style.color,
        weight: style.weight,
        opacity: 0.8,
      }).bindTooltip(edgeLabel(source, target), { sticky: true }));
    }
  }
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

// Show the design's tier tallies in the top-right of the bar. CORE (standalone
// cores) and CORE+AGGR (dual-role cores) appear only when the design has any;
// AGGR counts standalone aggregations only, so a dual-role core is never
// double-counted across the CORE+AGGR and AGGR tallies.
function showCounts(summary) {
  const counts = document.getElementById("counts");
  const parts = [];
  if (summary.standalone_core_count) {
    parts.push(`CORE ${summary.standalone_core_count}`);
  }
  if (summary.colocated_core_count) {
    parts.push(`CORE+AGGR ${summary.colocated_core_count}`);
  }
  parts.push(`AGGR ${summary.standalone_aggregation_count}`);
  parts.push(`ACCESS ${summary.access_vertex_count}`);
  counts.textContent = parts.join(" ");
}

async function render(mapId) {
  clear();
  const [vertices, edges, summary] = await Promise.all([
    getJSON(`/api/wan-maps/${mapId}/vertices`),
    getJSON(`/api/wan-maps/${mapId}/edges`),
    getJSON(`/api/wan-maps/${mapId}/summary`),
  ]);
  showCounts(summary);

  const byId = indexById(vertices);
  drawEdges(pathsByPurpose(edges.path_uses, "core_mesh"), byId, EDGE_STYLE.backbone);
  drawEdges(
    pathsByPurpose(edges.path_uses, "aggregation_to_core"),
    byId, EDGE_STYLE.aggregation,
  );
  drawEdges(edges.access_edges, byId, EDGE_STYLE.access);
  const points = drawVertices(vertices);

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
