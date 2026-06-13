# WAN Graph Designer

WAN Graph Designer is a web application for designing wide area network
layouts as mathematical graphs. In this context, a graph is limited to
nodes and edges: nodes represent network locations, and edges represent
allowed connections between those locations.

The application accepts structured inputs and renders the resulting WAN
graph as a webpage. Graphviz is used as the graph rendering engine.

## Inputs

- **Sites** (required) — network locations represented as graph nodes.
- **Aggregation points** (optional) — intermediate locations that
  collect traffic from sites.
- **Core sites** (optional) — central locations that connect to
  aggregation points and to each other.
- **Edges** (optional) — explicit connections between supported node
  types.

Sites, aggregation points, and core sites each include:

- **Location** — a town, city, county, or military base.
- **U.S. state** — the state where the location exists.
- **Bandwidth** — the bandwidth required or available at the node.

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
  node-disjoint paths, so no single PoP or link failure can sever it
  from the core tier.
- The core sites form a full mesh: every core connects to every other
  core.
- A PoP needs at least two physical links to be eligible as an
  aggregation or core node; degree-one spurs cannot be dual-homed.

## Output

The output is a webpage that displays the WAN graph. The rendered graph
contains only nodes and edges, using Graphviz as the layout and
rendering engine.

## Carrier three-tier WAN design script

Use `scripts/design_network.py` to compute a three-tier WAN design
from the included KMZ and the Carrier mapbook-derived edge list:

```bash
python3 scripts/design_network.py
```

The script parses F-35, Sentinel, CSP Secret region, and Carrier 400G PoP
placemarks. F-35, Sentinel, and CSP Secret locations are access nodes.
The script selects up to three Carrier core PoPs, selects aggregation PoPs
as needed, dual-homes every access node to two aggregation PoPs, routes
every aggregation to two cores over node-disjoint paths on the physical
Carrier graph, and meshes the cores. The run fails if any aggregation
cannot reach two cores disjointly or the cores are not a full mesh.

The edge list in `data/carrier_edges.csv` is transcribed from the carrier's
publicly published network map. Results are written to
`outputs/` as JSON, CSV, KML, and Graphviz DOT files.

Tune the core tier:

```bash
python3 scripts/design_network.py \
  --core-count 3 \
  --min-core-separation-miles 750
```

Inspect the raw tier assignment without extra resilience augmentation:

```bash
python3 scripts/design_network.py --no-resilience-augmentation
```

## Testing

Tests follow the standard pyramid under `test/`:

```bash
PYTHONPATH=scripts python3 -m pytest test/unit
PYTHONPATH=scripts python3 -m pytest test/integration
PYTHONPATH=scripts python3 -m pytest test/e2e
```
