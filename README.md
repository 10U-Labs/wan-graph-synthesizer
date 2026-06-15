# WAN Graph Designer

WAN Graph Designer is a web application for designing wide area network
layouts as mathematical graphs. In this context, a graph is limited to
vertices and edges: vertices represent network locations, and edges represent
allowed connections between those locations.

The application accepts structured inputs and renders the resulting WAN
graph as a webpage. Graphviz is used as the graph rendering engine.

## Inputs

- **Sites** (required) — network locations represented as graph vertices.
- **Aggregation points** (optional) — intermediate locations that
  collect traffic from sites.
- **Core sites** (optional) — central locations that connect to
  aggregation points and to each other.
- **Edges** (optional) — explicit connections between supported vertex
  types.

Sites, aggregation points, and core sites each include:

- **Location** — a town, city, county, or military base.
- **U.S. state** — the state where the location exists.
- **Bandwidth** — the bandwidth required or available at the vertex.

## Edges and design rules

Edges are tuples of one of the supported connection types:

| Edge type                      | Tuple                            |
| ------------------------------ | -------------------------------- |
| Site to aggregation point      | `(site, aggregation_point)`      |
| Aggregation point to core site | `(aggregation_point, core_site)` |
| Core site to core site         | `(core_site, core_site)`         |

The resilience rules the design enforces:

- Every site dual-homes to two distinct aggregation points.
- Every aggregation point reaches two distinct core sites over two
  vertex-disjoint paths, so no single PoP or link failure can sever it
  from the core tier.
- The core sites form a full mesh: every core connects to every other
  core.
- A PoP needs at least two physical links to be eligible as an
  aggregation or core vertex; degree-one spurs cannot be dual-homed.

## Output

The output is a self-hosted web app: an interactive Leaflet map that
redraws as you pick a tenant view. There is no manual export step.

## Data and WAN map configs

Vertices live in `data/vertices/`, one CSV per tenant (`lumen.csv`,
`dcn.csv`, `f_35.csv`, `aws.csv`, ...), each row with columns
`name,latitude,longitude,kind,shown_in_map,description`. The tenant is the
file, and the `kind` column classifies each vertex (`PoP`/`ROADM` carrier
PoPs versus `Military installation`, `CSP data center`, `UARC`, and
`Corporate office` access vertices). The edge files in `data/edges/` are
transcribed from the carriers' published network maps.

Each WAN map is a config in `etc/`: `joint.yml` lists every tenant file;
`f_35.yml` is an F-35-only variant that omits AFLCMC and AFNWC/NI. The
config also carries every design choice — core count, forced cores and
aggregations, exclusions, and resilience augmentation — so tuning a design
means editing the YAML, never source.

The design selects up to three Carrier core PoPs, selects aggregation PoPs
as needed, dual-homes every access vertex to two aggregation PoPs, routes
every aggregation to two cores over vertex-disjoint paths on the physical
Carrier graph, and meshes the cores. A design that cannot reach two cores
disjointly, or whose cores are not a full mesh, is reported as invalid by
the `validation` endpoint.

## Web app

Run the self-hosted web app and pick a tenant view in the browser. It
serves a REST API and a Leaflet map from one process; designs are computed
on demand from the configs in `etc/` (Joint, F-35) and cached in memory:

```bash
pip install -r requirements.txt
PYTHONPATH=lib/python:src python3 src/serve.py
```

Then open `http://localhost:8000` and choose **Joint** or **F-35** from
the dropdown; the map redraws with the cores, aggregations, access
vertices, and edges as toggleable layers, plus a validation banner.

The REST surface is a set of atomic resources (WAN map `id` = `joint`
or `f_35`):

- `GET /api/wan-maps` — selectable WAN maps (`id`, `label`)
- `GET /api/wan-maps/{id}/vertices` — vertices with tier role and coordinates
- `GET /api/wan-maps/{id}/edges` — access, physical, and routed edges
- `GET /api/wan-maps/{id}/validation` — the structural validation report
- `GET /api/wan-maps/{id}/summary` — tier counts, mileage, chosen cores

Everything is free and open-source and runs locally. The one external
dependency is the OpenStreetMap *tile* server (`TILE_URL` in
`src/www/app.js`); point it at a self-hosted tile server to run fully
offline.

To tune a design — the core count, forced cores or aggregations,
exclusions, or resilience augmentation — edit the WAN map's config in
`etc/` and reload the page; the design recomputes on the next request.

## Testing

Tests follow the standard pyramid under `test/`:

```bash
PYTHONPATH=lib/python:src python3 -m pytest test/unit
PYTHONPATH=lib/python:src python3 -m pytest test/integration
PYTHONPATH=lib/python:src python3 -m pytest test/e2e
```
