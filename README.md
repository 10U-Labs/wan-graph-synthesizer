# WAN Graph Designer

WAN Graph Designer is a web application for designing wide area network layouts
as mathematical graphs. In this context, a graph is limited to nodes and edges:
nodes represent network locations, and edges represent allowed connections
between those locations.

The application accepts structured inputs and renders the resulting WAN graph as
a webpage. Graphviz is used as the graph rendering engine.

## Inputs

| Input              | Required | Description                                                            |
| ------------------ | -------- | ---------------------------------------------------------------------- |
| Sites              | Yes      | Network locations that must be represented as graph nodes.             |
| Aggregation points | No       | Intermediate network locations that can collect traffic from sites.    |
| Core sites         | No       | Central network locations that can connect to aggregation points.      |
| Edges              | No       | Explicit connections between supported node types.                     |

Sites, aggregation points, and core sites must include the following fields:

| Field      | Description                                      |
| ---------- | ------------------------------------------------ |
| Location   | A town, city, county, or military base.          |
| U.S. state | The state where the location exists.             |
| Bandwidth  | The bandwidth required or available at the node. |

Edges must be defined as a tuple using one of the supported connection types:

| Edge Type                      | Tuple                              |
| ------------------------------ | ---------------------------------- |
| Site to aggregation point      | `(site, aggregation_point)`        |
| Aggregation point to core site | `(aggregation_point, core_site)`   |

## Output

The output is a webpage that displays the WAN graph. The rendered graph should
contain only nodes and edges, using Graphviz as the layout and rendering engine.
