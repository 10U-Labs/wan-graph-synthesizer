"use strict";

// Self-hosted Leaflet over OpenStreetMap. To run fully offline, point TILE_URL
// at a local tile server (e.g. tileserver-gl) instead of openstreetmap.org.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = "© OpenStreetMap contributors";

// Tier styling: color and circle radius per tier role.
const TIER_STYLE = {
  core: { color: "#c62828", radius: 8, group: "Cores" },
  aggregation: { color: "#00897b", radius: 6, group: "Aggregations" },
  access: { color: "#f9a825", radius: 4, group: "Access" },
  transit: { color: "#757575", radius: 3, group: "Carrier PoPs" },
  unused: { color: "#757575", radius: 3, group: "Carrier PoPs" },
};

// Which overlay groups start visible (the carrier backbone is busy, so off).
const DEFAULT_ON = new Set([
  "Cores",
  "Aggregations",
  "Access",
  "Access links",
  "Backbone routes",
]);

const map = L.map("map").setView([39.5, -98.35], 4);
L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(map);

let overlays = [];
let layerControl = null;

function styleFor(role) {
  return TIER_STYLE[role] || TIER_STYLE.unused;
}

function vertexPopup(vertex) {
  return `<strong>${vertex.name}</strong><br>${vertex.tenant} — ${vertex.kind}` +
    `<br>role: ${vertex.tier_role}`;
}

// Build one Leaflet layer group per tier; return {group name: layerGroup}.
function vertexGroups(vertices, coordsById) {
  const groups = {};
  for (const vertex of vertices) {
    coordsById[vertex.id] = vertex.coords;
    const style = styleFor(vertex.tier_role);
    const marker = L.circleMarker(vertex.coords, {
      radius: style.radius,
      color: style.color,
      fillColor: style.color,
      fillOpacity: 0.85,
      weight: 1,
    }).bindPopup(vertexPopup(vertex));
    (groups[style.group] = groups[style.group] || L.layerGroup()).addLayer(marker);
  }
  return groups;
}

// Build a polyline layer group from edges that carry source_id/target_id.
function edgeGroup(edges, coordsById, color, weight) {
  const group = L.layerGroup();
  for (const edge of edges) {
    const a = coordsById[edge.source_id];
    const b = coordsById[edge.target_id];
    if (a && b) {
      group.addLayer(L.polyline([a, b], { color, weight, opacity: 0.7 }));
    }
  }
  return group;
}

function setStatus(validation, summary) {
  const ok = validation.connected &&
    validation.aggregations_dual_homed_to_cores &&
    validation.cores_full_mesh;
  const status = document.getElementById("status");
  status.className = ok ? "valid" : "invalid";
  status.textContent = (ok ? "✓ valid" : "✗ invalid") +
    ` — ${summary.core_count} cores, ${summary.aggregation_count} aggregations, ` +
    `${summary.access_vertex_count} access`;
}

function resetOverlays() {
  for (const layer of overlays) {
    map.removeLayer(layer);
  }
  if (layerControl) {
    map.removeControl(layerControl);
  }
  overlays = [];
}

// Add a named overlay: track it, show it if on by default, and collect it for
// the layer control.
function addOverlay(named, name, layer) {
  named[name] = layer;
  overlays.push(layer);
  if (DEFAULT_ON.has(name)) {
    layer.addTo(map);
  }
}

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} → ${response.status}`);
  }
  return response.json();
}

async function render(mapId) {
  resetOverlays();
  const [vertices, edges, validation, summary] = await Promise.all([
    getJSON(`/api/wan-maps/${mapId}/vertices`),
    getJSON(`/api/wan-maps/${mapId}/edges`),
    getJSON(`/api/wan-maps/${mapId}/validation`),
    getJSON(`/api/wan-maps/${mapId}/summary`),
  ]);

  const coordsById = {};
  const named = {};
  const groups = vertexGroups(vertices, coordsById);
  for (const name of Object.keys(groups)) {
    addOverlay(named, name, groups[name]);
  }
  addOverlay(named, "Access links", edgeGroup(edges.access_edges, coordsById, "#f9a825", 1.5));
  addOverlay(named, "Backbone routes", edgeGroup(edges.path_uses, coordsById, "#1565c0", 2.5));
  addOverlay(named, "Carrier backbone", edgeGroup(edges.physical_edges, coordsById, "#9e9e9e", 1));

  layerControl = L.control.layers(null, named, { collapsed: false }).addTo(map);
  setStatus(validation, summary);

  const points = vertices.map((vertex) => vertex.coords);
  if (points.length) {
    map.fitBounds(points, { padding: [30, 30] });
  }
}

async function init() {
  const select = document.getElementById("config");
  const wanMaps = await getJSON("/api/wan-maps");
  for (const wanMap of wanMaps) {
    const option = document.createElement("option");
    option.value = wanMap.id;
    option.textContent = wanMap.label;
    select.appendChild(option);
  }
  select.addEventListener("change", () => render(select.value));
  if (wanMaps.length) {
    await render(wanMaps[0].id);
  }
}

init().catch((error) => {
  document.getElementById("status").textContent = `Error: ${error.message}`;
});
