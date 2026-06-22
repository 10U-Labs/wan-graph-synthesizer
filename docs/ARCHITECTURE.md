# Architecture

How WAN Graph Designer is built, deployed, and served.

## Purpose

Interconnect a customer's installations with each other — a wide-area network
tying their own sites together over shared carrier fiber — and give those
installations reach to the cloud providers (CSPs). The core and aggregation
hubs exist primarily to knit the installations together; CSP reach is an added
destination. Installations are the center of gravity, not the CSPs.

## Domain model: three kinds of graph

Every graph is vertices + edges + properties. A vertex's `kind` is one of:

- `pop` — belongs to a carrier
- `csp` — a cloud region (a `provider`: aws, azure, or oci)
- `installation` — belongs to a customer

The graph kinds:

- **carrier** — authored input; PoPs + fiber (lumen, zayo, uniti, cogent,
  vision-net, dcn).
- **csp** — authored input; regions only, no edges (aws, azure, oci).
- **substrate** — derived; all carriers stitched into one shared fiber mesh.
  It is a singleton, read and created via `carriers/merge`. Carriers are the
  only genuinely shared input.
- **customer → wan** — derived; optimize over the substrate plus this
  customer's installations and its selected CSP regions, tiered into core /
  aggregation / access (f-35, joint, military-installations).

Lineage: carriers → (merge) → substrate → (+ installations, optimize) → a
customer's WAN.

A customer has exactly one WAN (a singleton, overwritten on each re-create).
CSP regions are per-customer (for example, F-35 uses only the secret-east
region of each provider); they are not part of the shared substrate.

## The REST API

Everything backend is a REST resource. The API is this repo's own API Gateway,
served at `api.10ulabs.com/wan-graph-designer/*`. Grammar: kebab-case, plural
collections, `{snake_case}` path params, no version segment.

Inputs are writable (`PUT` / `POST` / `DELETE`); computed graphs are read-only
(`GET`).

Inputs (writable):

```text
/carriers/{carrier}/vertices
/carriers/{carrier}/edges
/csps/{provider}/vertices
/customers/{customer}/installations
/customers/{customer}/csp-regions
/customers/{customer}/forced-core-nodes
/customers/{customer}/forced-aggregation-points
/customers/{customer}/prohibited-core-nodes
/customers/{customer}/prohibited-aggregation-points
/customers/{customer}/forced-edges
/customers/{customer}/prohibited-edges
```

Creates (produce derived graphs):

```text
POST /carriers/merge            -> the substrate (fast, synchronous)
POST /customers/{customer}/wan  -> the customer's WAN (async -> 202)
```

Reads (the latest successful results):

```text
GET /carriers/merge/vertices
GET /carriers/merge/edges
GET /customers/{customer}/wan
GET /customers/{customer}/vertices
GET /customers/{customer}/edges
GET /customers/{customer}/core-nodes
GET /customers/{customer}/aggregation-points
GET /customers/{customer}/access-nodes
```

A create either returns the graph or errors `422` if no valid WAN is possible.
There is no separate "validate" step and no "violations" resource: validity is
the create's success or failure. `kind` and `tier` are vertex properties; the
tier collections are views over `/vertices`.

### Inputs and the auto-create cascade

The only way to change an input is the HTTPS write endpoint. A write persists
to the store and auto-creates the dependent graph(s):

- a customer input — re-creates that customer's WAN
- a CSP — re-creates the WANs of customers using it
- a carrier — re-creates the substrate, then every customer's WAN

Inputs are authored in git (`data/`, `etc/`) for review and history; a CI
client (`scripts/seed.py`) reads changed files and issues the same `PUT`s. git is
an authoring convenience — the API store (S3) is the source of truth. A person,
script, or UI issuing the same `PUT` is identical.

## How it runs on AWS (OpenTofu)

Reuses the `../10ulabs.com` precedent: account 781581267945, us-east-2, the
shared state bucket `10ulabs-terraform-state-us-east-2`, and GitHub OIDC.

- **Website** — static, synced to `s3://www-10ulabs-com/wan-graph-designer/`,
  served at `10ulabs.com/wan-graph-designer/`. The public path comes from the
  sync destination, not a nested folder.
- **API host** — `api.10ulabs.com` is a CloudFront distribution that
  path-routes to origins. This repo is wired in once with one origin (its API
  Gateway) plus one behavior for `/wan-graph-designer/*`. The wildcard means
  new endpoints need no further `10ulabs.com` changes.
- **Read endpoints** — Lambdas (Python 3.13) that serve stored JSON from S3.
- **`carriers/merge`** — a fast Lambda that stitches all carriers into the
  substrate.
- **`customers/{c}/wan`** — `POST` starts a single Fargate Spot task that runs
  the whole pipeline (home, constrain, optimize, validate) in memory and writes
  the WAN JSON to S3, or records a `422` reason. Async because the optimizer
  can exceed API Gateway's ~29s synchronous cap; Spot because a create is
  fully retryable.
- **Store** — S3 JSON files. One format (JSON) end to end: the same JSON a step
  produces is what the API serves; no internal serialization.
- **Idle cost** is static hosting plus S3 storage only; the optimizer runs only
  during a create.

## Code layout

- `data/` — git-authored inputs, grouped by concept (`carriers/`, `csps/`,
  `customers/`).
- `etc/` — operator settings per customer.
- `lib/python/wan_designer/` — core logic, reused by every endpoint and the
  optimizer.
- `lib/opentofu/` — only OpenTofu modules reused across stacks.
- `src/api/common/` — shared infra: the API Gateway (`routing/`) and the S3
  bucket (`storage/`).
- `src/api/endpoints/` — one folder per resource: `carriers`, `csps`,
  `customers`, `merge`, `wan` (with `wan/optimizer/` for the container).
- `src/www/spa/` — the static single-page UI (synced to the site root);
  `src/www/api/` — the OpenAPI spec (deployed separately).
- `docs/tenets/tests/` — the four test tiers, per `10ulabs.com`.

Reusable code lives in `lib/`; single-use code lives in its `src/` stack. The
shared graph interchange — the vertex/edge types and the input-graph JSON codec
— is `lib/python/wan_graph/`; the optimizer's own design vocabulary, pipeline
steps (`wan_designer/stages.py`), and per-collection JSON views
(`wan_designer/collections.py`) live with the optimizer engine. The inputs
script's CSV readers live in `scripts/seed.py`.

## Out of scope (deferred)

Live server-side graph queries (trace-path, what-fails-if, e.g. via Neptune)
against the full network are a future product, not built here.
