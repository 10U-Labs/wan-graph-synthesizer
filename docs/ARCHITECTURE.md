# Architecture

How WAN Graph Designer is built, deployed, and served.

## Purpose

Interconnect a customer's **installations with each other** — a wide-area network tying their
own sites together over shared carrier fiber — **and** give those installations reach to the
cloud providers (providers). The core/aggregation hubs exist primarily to knit the installations
together; provider reach is an added destination. Installations are the center of gravity, not the
providers.

## Domain model: three kinds of graph

Every graph is **vertices + edges + properties**. A vertex's `kind` is `pop` (belongs to a
carrier), `provider` (a cloud region; `provider` ∈ aws/provider/provider), or `installation` (belongs to a
customer).

| Graph | How it's produced | Tiered? | Examples |
|-------|-------------------|---------|----------|
| **carrier** | authored input — PoPs + fiber | no | lumen, zayo, uniti, cogent, vision-net, dcn |
| **provider** | authored input — regions only, no edges | no | aws, provider, provider |
| **substrate** | derived — **all carriers stitched** into one shared fiber mesh (carriers are the *only* genuinely shared input); read/created via `carriers/merge` | no | (singleton) |
| **customer → wan** | derived — `optimize(substrate + this customer's installations + its selected provider regions)`; tiered into **core / aggregation / access** | yes | f-35, joint, military-installations |

Lineage: `carriers ──merge──▶ substrate ──+ installations, optimize──▶ a customer's WAN`.

A customer has exactly **one** WAN (a singleton, overwritten on each re-create). provider regions
are **per-customer** (e.g. F-35 uses only the *provider region* region of each provider) — they are
not part of the shared substrate.

## The REST API

Everything backend is a REST resource. The API is this repo's **own** API Gateway, served at
`api.10ulabs.com/wan-graph-designer/*`. Grammar: kebab-case, plural collections,
`{snake_case}` path params, no version segment.

**Inputs are writable** (`PUT`/`POST`/`DELETE`); **computed graphs are read-only** (`GET`).

```
# Inputs (writable) — the source of truth lives in the API store
…/carriers/{carrier}/vertices · edges
…/providers/{provider}/vertices
…/customers/{customer}/installations · provider-regions
…/customers/{customer}/forced-core-nodes · forced-aggregation-points
…/customers/{customer}/prohibited-core-nodes · prohibited-aggregation-points
…/customers/{customer}/forced-edges · prohibited-edges

# Creates (produce derived graphs)
POST …/carriers/merge                 → the substrate (fast, synchronous)
POST …/customers/{customer}/wan       → the customer's WAN (async → 202)

# Reads (the latest successful results)
GET  …/carriers/merge/vertices · edges                    # the substrate
GET  …/customers/{customer}/wan                           # the WAN + its status, or a 422 reason
GET  …/customers/{customer}/vertices · edges
GET  …/customers/{customer}/core-nodes · aggregation-points · access-nodes
```

- A create either returns the graph or **errors `422`** if no valid WAN is possible. There is no
  separate "validate" step and no "violations" resource — validity is the create's success/fail.
- `kind` and `tier` are vertex **properties**; `core-nodes` / `aggregation-points` /
  `access-nodes` are tier-filtered views over `/vertices`.

### Inputs and the auto-create cascade

The **only** way to change an input is the HTTPS write endpoint. A write persists to the store
and **auto-creates the dependent graph(s)**:

- write a **customer** input → re-create that customer's WAN
- write a **provider** → re-create the WANs of customers using it
- write a **carrier** → re-create the substrate (merge), then **every** customer's WAN

Inputs are authored in git (`data/`, `etc/`) for review/history; a CI client (`push_inputs`)
reads changed files and issues the same `PUT`s. git is an authoring convenience — the API store
(S3) is the source of truth. A person, script, or UI issuing the same `PUT` is identical.

## How it runs on AWS (OpenTofu)

Reuses the `../10ulabs.com` precedent (account `781581267945`, `us-east-2`, shared state bucket
`10ulabs-terraform-state-us-east-2`, GitHub OIDC).

- **Website** — static, synced to `s3://www-10ulabs-com/wan-graph-designer/`, served at
  `10ulabs.com/wan-graph-designer/`. The public path comes from the sync destination, not a
  nested folder.
- **API host** — `api.10ulabs.com` is a CloudFront distribution that path-routes to origins.
  This repo is wired in **once** with one `origin` (its API Gateway) + one
  `ordered_cache_behavior { path_pattern = "/wan-graph-designer/*" }`. The wildcard means new
  endpoints need zero further `10ulabs.com` changes.
- **Read endpoints** — Lambdas (Python 3.13) that serve stored JSON from S3.
- **`carriers/merge`** — a fast Lambda that stitches all carriers into the substrate.
- **`customers/{c}/wan`** — `POST` starts a single **Fargate Spot** task that runs the whole
  pipeline `home → constrain → optimize → validate` in-memory and writes the WAN JSON to S3 (or a
  `422` reason). Async because the optimizer can exceed API Gateway's ~29s synchronous cap; Spot
  because a create is fully retryable.
- **Store** — S3 JSON files. One format (JSON) end to end — the same JSON a step produces is what
  the API serves; no internal/secondary serialization.
- **Idle cost** ≈ static hosting + S3 storage only; the optimizer runs solely during a create.

## Code layout

```
data/{carriers/<c>/{vertices,edges}.csv, providers/<p>/<region>.csv, customers/<c>.csv}   # git-authored inputs
etc/<customer>.yml                                                                    # operator settings
lib/python/wan_designer/        # core logic (reused by every endpoint + the optimizer)
lib/opentofu/                   # only OpenTofu modules reused across stacks
src/api/common/{routing,storage}/     # shared: the API Gateway, the S3 bucket
src/api/endpoints/{carriers,providers,customers,merge,wan}/   # one folder per resource (+ wan/optimizer/ container)
src/www/                        # the static UI
docs/tenets/tests/              # the four test tiers, per 10ulabs.com
```

Reusable code lives in `lib/`; single-use code lives in its `src/` stack. The optimizer and the
existing `design_payload` logic are unchanged — relocated into pipeline steps
(`lib/python/wan_designer/stages.py`) and per-collection JSON serializers
(`lib/python/wan_designer/graphs.py`), not rewritten.

## Out of scope (deferred)

Live server-side graph queries (trace-path / what-fails-if, e.g. via Neptune) against the full
network are a future product, not built here.
