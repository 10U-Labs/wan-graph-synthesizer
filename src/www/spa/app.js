"use strict";

// Self-hosted Leaflet over OpenStreetMap. To run fully offline, point TILE_URL
// at a local tile server (e.g. tileserver-gl) instead of openstreetmap.org.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIB = "© OpenStreetMap contributors";

// The REST API: a tenant's WAN is served as sites + links collections.
const API_BASE = "https://api.10ulabs.com/wan-graph-synthesizer";

// The tenant shown on first load, before the operator picks one.
const DEFAULT_MAP_ID = "daf";

// Site color and radius. Provider regions are colored by kind; every other drawn
// site is colored by its tier role. Transit/unused carrier PoPs are not drawn.
const PROVIDER_KIND = "provider region";
const PROVIDER_STYLE = { color: "#ef6c00", radius: 5 };
const ROLE_STYLE = {
  backbone: { color: "#6a1b9a", radius: 8 },
  tenant: { color: "#1565c0", radius: 4 },
};

// The two drawn link kinds: the thick backbone carries the meshed carrier graph
// between backbone nodes; the thin access links home demand to the backbone.
const LINK_STYLE = {
  access: { color: ROLE_STYLE.tenant.color, weight: 1.5 },
  backbone: { color: ROLE_STYLE.backbone.color, weight: 4.5 },
};

// The CONUS center the map opens on; also the meridian every site is anchored
// to, so far-side-of-the-antimeridian sites render on the world copy nearest it.
const VIEW_CENTER = [39.5, -98.35];

// The legend, one row per drawn symbol, in the map's bottom-right corner. The
// tenant row is relabelled with the selected tenant, so it reads "DAF Location".
const LEGEND_ROWS = [
  { swatch: "dot", color: ROLE_STYLE.backbone.color, label: "WAN Backbone Node" },
  { swatch: "dot", color: PROVIDER_STYLE.color, label: "Provider" },
  { swatch: "dot", color: ROLE_STYLE.tenant.color, label: "Location", tenant: true },
  { swatch: "line", color: LINK_STYLE.backbone.color, label: "Fiber" },
];

const map = L.map("map").setView(VIEW_CENTER, 4);
L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(map);

let drawn = [];

// The tenant row's text node, held so selecting a tenant can relabel it.
let tenantLegendText = null;

const legend = L.control({ position: "bottomright" });

legend.onAdd = function onAdd() {
  const box = L.DomUtil.create("div", "legend");
  for (const row of LEGEND_ROWS) {
    const item = L.DomUtil.create("div", "legend-item", box);
    const swatch = L.DomUtil.create("span", `legend-swatch legend-${row.swatch}`, item);
    swatch.style.background = row.color;
    const text = L.DomUtil.create("span", "legend-label", item);
    text.textContent = row.label;
    if (row.tenant) {
      tenantLegendText = text;
    }
  }
  L.DomEvent.disableClickPropagation(box);
  return box;
};

legend.addTo(map);

// Name the legend's blue dot after the tenant on show, e.g. "DAF Location".
function showLegendTenant(label) {
  if (tenantLegendText) {
    tenantLegendText.textContent = `${label} Location`;
  }
}

function styleFor(site) {
  if (site.kind === PROVIDER_KIND) {
    return PROVIDER_STYLE;
  }
  return ROLE_STYLE[site.tier_role] || null;
}

// Tier-role label prefixes, so every backbone site tooltip announces its role
// up front. Demand sites (tenant, provider) and transit nodes get no prefix.
const TIER_PREFIX = {
  backbone: "BACKBONE",
};

// The bare city: the site name stripped of any trailing ", Region" (a US state or a
// country), so the role-prefixed name reads "BACKBONE Los Angeles" / "BACKBONE Tokyo",
// never "BACKBONE Los Angeles, CA" or "BACKBONE Tokyo, Japan".
function cityName(site) {
  return site.name.replace(/,\s*[^,]+$/, "");
}

// Role-prefixed display name, e.g. "BACKBONE Los Angeles". Demand sites
// (tenant, provider) and transit nodes keep their full name unchanged.
function displayName(site) {
  const prefix = TIER_PREFIX[site.tier_role];
  return prefix ? `${prefix} ${cityName(site)}` : site.name;
}

// Tooltip: the role-prefixed display name and its location beneath. The location reads
// "City, State" for US places and "City, Country" for everywhere else.
function siteLabel(site) {
  const info = site.info || {};
  const region = info.country === "United States" ? info.state : info.country;
  const located = info.municipality && region
    ? `<br>${info.municipality}, ${region}`
    : "";
  return `<strong>${displayName(site)}</strong>${located}`;
}

function linkLabel(source, target) {
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

// Build a site's circle marker at the given coordinates, or null for
// transit/unused carrier PoPs (which are not drawn).
function siteMarker(site, coords) {
  const style = styleFor(site);
  if (!style) {
    return null;
  }
  return L.circleMarker(coords, {
    radius: style.radius,
    color: style.color,
    fillColor: style.color,
    fillOpacity: 0.85,
    weight: 1,
  }).bindTooltip(siteLabel(site));
}

// Shift a longitude onto the copy of the world nearest the map's center
// meridian, so a far-side-of-the-antimeridian site (e.g. the Marshall Islands
// at 167.7°E) renders on the copy just west of CONUS, not off the east link.
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

// A site's drawing coordinates, with its longitude anchored to the CONUS copy.
function displayCoords(site) {
  return [site.coords[0], nearLon(site.coords[1])];
}

// Index the sites by id so links can resolve their endpoints. Drawing is
// deferred to drawSites so markers land on top of the links.
function indexById(sites) {
  const byId = {};
  for (const site of sites) {
    byId[site.id] = site;
  }
  return byId;
}

// Draw every tiered site at its CONUS-anchored position; skip transit/unused
// carrier PoPs. Returns the drawn coordinates so fitBounds can frame them.
function drawSites(sites) {
  const coords = [];
  for (const site of sites) {
    const at = displayCoords(site);
    const marker = siteMarker(site, at);
    if (marker) {
      add(marker);
      coords.push(at);
    }
  }
  return coords;
}

// Draw one set of links in the given tier style, each with a hover tooltip.
// Endpoints use CONUS-anchored coordinates, so a trans-Pacific link is drawn the
// short way to the world copy beside CONUS rather than the long way east.
function drawLinks(links, byId, style) {
  for (const link of links) {
    const source = byId[link.source_id];
    const target = byId[link.target_id];
    if (source && target) {
      add(L.polyline([displayCoords(source), displayCoords(target)], {
        color: style.color,
        weight: style.weight,
        opacity: 0.8,
      }).bindTooltip(linkLabel(source, target), { sticky: true }));
    }
  }
}

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} → ${response.status}`);
  }
  return response.json();
}

// Show the WAN's tier tallies in the top-right of the bar, counted from the
// served sites (each carries its tier_role and whether it was included).
function showCounts(sites) {
  const counts = document.getElementById("counts");
  const tally = { backbone: 0, tenant: 0, provider: 0 };
  for (const site of sites) {
    if (site.included !== false && tally[site.tier_role] !== undefined) {
      tally[site.tier_role] += 1;
    }
  }
  counts.textContent = `POPS ${tally.backbone} TENANTS ${tally.tenant} PROVIDERS ${tally.provider}`;
}

async function render(tenantId) {
  clear();
  let sites;
  let links;
  try {
    [sites, links] = await Promise.all([
      getJSON(`${API_BASE}/tenants/${tenantId}/sites`),
      getJSON(`${API_BASE}/tenants/${tenantId}/paths`),
    ]);
  } catch (error) {
    document.getElementById("counts").textContent = "WAN not built yet";
    return;
  }
  showCounts(sites);

  const byId = indexById(sites);
  const physical = links.filter((link) => link.link_kind === "carrier_physical");
  const access = links.filter(
    (link) => link.link_kind === "tenant_to_backbone" || link.link_kind === "provider_to_backbone",
  );
  drawLinks(physical, byId, LINK_STYLE.backbone);
  drawLinks(access, byId, LINK_STYLE.access);
  const points = drawSites(sites);

  if (points.length) {
    map.fitBounds(points, { padding: [30, 30] });
  }
}

// Mark the chosen tenant link active, name it in the legend, and redraw its map.
function select(link, mapId) {
  for (const other of document.querySelectorAll("#tenants a")) {
    other.classList.toggle("active", other === link);
  }
  showLegendTenant(link.textContent);
  return render(mapId);
}

async function init() {
  const nav = document.getElementById("tenants");
  const tenants = await getJSON(`${API_BASE}/tenants`);
  const entries = tenants.map(({ id, label }) => {
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = label;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      select(link, id);
    });
    nav.appendChild(link);
    return { link, id };
  });
  const start = entries.find((entry) => entry.id === DEFAULT_MAP_ID) || entries[0];
  if (start) {
    await select(start.link, start.id);
  }
}

init().catch((error) => {
  console.error(error);
});
