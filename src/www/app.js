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
  core: { color: "#c62828", radius: 8 },
  aggregation: { color: "#6a1b9a", radius: 6 },
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

function vertexLabel(vertex) {
  return `<strong>${vertex.name}</strong><br>${vertex.tier_role} · ${vertex.kind}` +
    `<br>${vertex.tenant}`;
}

function edgeLabel(label, source, target) {
  return `${label}<br><strong>${source.name}</strong> ↔ <strong>${target.name}</strong>`;
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

// Draw every tiered vertex; skip transit/unused carrier PoPs. Returns the
// vertices indexed by id so edges can resolve their endpoints.
function drawVertices(vertices) {
  const byId = {};
  for (const vertex of vertices) {
    byId[vertex.id] = vertex;
    const style = styleFor(vertex);
    if (!style) {
      continue;
    }
    add(L.circleMarker(vertex.coords, {
      radius: style.radius,
      color: style.color,
      fillColor: style.color,
      fillOpacity: 0.85,
      weight: 1,
    }).bindTooltip(vertexLabel(vertex)));
  }
  return byId;
}

// Draw one set of edges in the given tier style, each with a hover tooltip.
function drawEdges(edges, byId, style, label) {
  for (const edge of edges) {
    const source = byId[edge.source_id];
    const target = byId[edge.target_id];
    if (source && target) {
      add(L.polyline([source.coords, target.coords], {
        color: style.color,
        weight: style.weight,
        opacity: 0.8,
      }).bindTooltip(edgeLabel(label, source, target), { sticky: true }));
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

async function render(mapId) {
  clear();
  const [vertices, edges] = await Promise.all([
    getJSON(`/api/wan-maps/${mapId}/vertices`),
    getJSON(`/api/wan-maps/${mapId}/edges`),
  ]);

  const byId = drawVertices(vertices);
  drawEdges(pathsByPurpose(edges.path_uses, "core_mesh"), byId, EDGE_STYLE.backbone, "Backbone");
  drawEdges(
    pathsByPurpose(edges.path_uses, "aggregation_to_core"),
    byId, EDGE_STYLE.aggregation, "Aggregation link",
  );
  drawEdges(edges.access_edges, byId, EDGE_STYLE.access, "Access link");

  const points = vertices.map((vertex) => vertex.coords);
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
