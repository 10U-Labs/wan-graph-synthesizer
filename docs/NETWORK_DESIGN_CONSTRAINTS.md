# WAN Design Constraints

This document is the source of truth for the three-tier WAN design
problem the optimizer solves. It complements `CONSTRAINTS.md`, which
covers platform and tooling constraints rather than the network design.

## Source of truth

The carrier topology and vertex roles come from the Lumen Next-Gen
Optical Network Mapbook (`LumenNetworkMapbook25`, five pages). The
mapbook is authoritative for how PoPs connect to each other.

It is transcribed into the edge files under `data/edges/`, which list
which PoPs are directly connected.

Vertices live in `data/vertices/`, one CSV per tenant (the tenant is the
file). A carrier PoP's `kind` is its role on the backbone: `PoP`
(aggregation-capable) or `ROADM` (transit only). The demand sites are the
remaining tenant files -- the F-35 installations, the Sentinel program
locations (`afnwc_ni.csv`), the additional CONUS installations
(`aflcmc.csv`), and the cloud Secret/CUI/Top Secret regions -- each row
tagged with its `kind`.

### The mapbook has no distances

The mapbook draws routes as geographic lines that follow real
right-of-way, not straight lines, and it lists no mileage. There is no
direct line between PoPs. Straight-line (haversine) distance between
PoPs must not be used as a design objective or cost. Distance may be
used only for last-mile circuits (a demand site to its aggregation
PoP), which are new builds rather than existing carrier routes.

## Hard constraints

A design is invalid unless all of the following hold.

1. Every access vertex homes to exactly `tuning.access_aggregation_links`
   aggregation points (default two).
2. Every aggregation point dual-homes to two distinct core vertices over
   vertex-disjoint paths.
3. Every core vertex links to its `tuning.core_links_per_core` nearest
   reachable cores on the backbone (fewer only when the core tier is
   smaller than that target).
4. There are at least three core vertices. More cores are allowed when
   needed for feasibility.
5. Only `aggregator` PoPs may serve as aggregation or core vertices.
   `roadm` PoPs are optical pass-through only and are never aggregation
   or core vertices.
6. Sentinel aggregation:
   - 165 sites aggregate toward Malmstrom AFB.
   - 165 sites aggregate toward Minot AFB.
   - 165 sites aggregate toward F.E. Warren AFB.
7. Strict tiering. Access vertices connect only to aggregation points;
   only aggregation points connect to cores. An access vertex never
   connects directly to a core, even when an aggregation and a core are
   co-located in the same building.
8. Co-location is allowed but identity is separate. A single PoP may
   host both a core and an aggregation. They are modeled as two distinct
   vertices that share coordinates (for example `AGGR Ashburn` and `CORE
   Ashburn`), never one vertex serving both roles. The two are distinct
   hardware stacks joined by a zero-mile in-facility cross-connect, so a
   co-located aggregation reaches its own co-located core as one of its
   two vertex-disjoint cores (constraint 2) and a remote core as the other.
   The core's fiber handoffs are duplicated onto the aggregation stack so
   that second, disjoint path leaves the building without traversing the
   core.

## Operator role pins

Beyond the algorithm, the operator may pin tier roles by PoP name. The
pins are keys under the `design:` block of a WAN map's config in `etc/`
(`joint.yml`, `f_35_non_redundant.yml`) — explicit data rather than hidden constants:

- `forced_cores: [NAME, ...]` makes each PoP a core. It is fixed into every
  candidate core set the search considers; the search still adds any
  further cores by strength.
- `forced_aggregations: [NAME, ...]` makes each PoP an aggregation. It is
  always selected, like a Sentinel base, but carries only the demand it
  actually homes, not the 165-site base demand.
- `excluded: [NAME, ...]` bars each PoP from every selected role: never a
  core, an aggregation, or an access home. It may still carry pass-through
  backbone fiber as a transit PoP.
- A PoP pinned as both a core and an aggregation is co-located: it is
  split into a `CORE` vertex (kept under the PoP's own name) and a
  co-located `AGGR` vertex, per hard constraint 8.

The canonical design pins Atlanta and Philadelphia as cores; and McLean,
Portland, San Luis Obispo, New York, and Richmond as aggregations. Two
Long Island demand intents are not Lumen PoPs in
the mapbook, so they are mapped to the nearest existing PoPs: Brookhaven
to New York, NY and Shirley to Newark, NJ.

## Aggregation tier: intentional clusters

Aggregation points are not placed per access site by nearest-distance.
They are placed as the heads of genuine clusters of access vertices, so a
new accredited facility is built only when it aggregates many
geographically close access vertices.

- Cluster the access vertices by density (DBSCAN). A cluster forms wherever
  at least **three** access vertices sit close together (the `N = 3`
  minimum-points parameter).
- The neighborhood radius `R` is **derived from the data** — the elbow
  of the sorted nearest-neighbor distances — not a hand-picked constant,
  consistent with this project's rejection of magic numbers. California,
  Florida, and Northern Virginia must fall out as clusters.
- Each cluster is served by aggregation points at **two distinct Lumen
  PoPs**, so its members dual-home over vertex-disjoint paths (hard
  constraint 1). The two PoPs are chosen for reachability and
  disjointness, not for being geographically central.

### Diversity and sparse access vertices by reuse

A new aggregation facility is built only to be a genuine cluster head.
Every other homing requirement is satisfied by reusing a facility that
already exists.

- A sparse, lone access vertex that belongs to no cluster homes to the
  nearest **existing** aggregation points (still two, still
  vertex-disjoint, both aggregations) over the carrier backbone.
- A site's second (diversity) home is always an existing facility —
  another cluster's aggregation, a Sentinel base, or an aggregation
  co-located with a core. No facility is ever stood up solely to serve
  as a backup.

This rule is what prevents redundant facilities (for example a separate
aggregation built only to be the Utah cluster's distant second home, or
a third aggregation inside a metro already served by two) from ever
being created, without any site-specific special-casing.

## Objective

Among all designs that satisfy the hard constraints, prefer the one
with the strongest core vertices. A PoP's strength has three parts,
weighted roughly equally:

- Reach: vertex degree, the number of PoPs it connects to directly.
- Spread: how many of the eight compass directions its links cover, so
  a core radiates outward instead of sitting on a thin corridor.
- Straightness: it can reach destinations without odd routes, that is,
  without large detours or near-90-degree turns.

The objective is not straight-line mileage and not hop count. Mileage
is rejected because the source has none. Hop count is rejected because
it does not capture reach or directness.

## Sentinel aggregation: resolved decisions

The Sentinel aggregation constraint (hard constraint 6) is modeled as
follows:

- The 165 sites per base are a modeled count, not individual locations.
  They are not sourced as placemarks; only the count and the
  aggregation relationship are modeled.
- Each base (Malmstrom AFB, Minot AFB, F.E. Warren AFB) is an
  aggregation point. It collects its 165 sites and dual-homes upward to
  two distinct core vertices over vertex-disjoint paths, like any
  aggregation point.
- The 165 sites single-home to their base. The two-aggregation rule
  (hard constraint 1) does not apply to them.

This constraint is layered on after the strength-based, three-core
optimizer rewrite lands.

## Facility and circuit costs

The network carries classified traffic under RED/BLACK separation
(CNSSAM TEMPEST/1-13), and every vertex is an accredited facility (ICD
705). Cost is in dollars, amortized straight-line over **one year**. It
is used as a reporting layer and to break ties between otherwise-equal
designs; it does not replace strength as the core-selection objective.

### One-time (capital)

- A standalone facility — a core alone or an aggregation alone — costs
  **$5.6M**: $600K TEMPEST / ICD 705 accreditation plus $5M of hardware
  (RED/BLACK crypto included).
- Adding the second function in the **same building** (a co-located
  core+aggregation pair) costs **about $2M more**, roughly $7.6M for the
  pair, because the accreditation is shared and only the footprint and
  gear are incremental. Two separate buildings would be $11.2M.
- Reusing a site that is already built and equipped — for example a
  Sentinel base that already acts as an aggregation — for additional
  homing costs **about $0** at the margin.

### Recurring (monthly)

- Colocation is **$50K per month** per facility (cross-connects
  included), scaling with footprint.
- Fiber is **tail-driven, never per route-mile**. A circuit's cost is
  the tail from a site to its nearest Lumen on-net PoP; PoP-to-PoP across
  the Lumen backbone is **free** (on-net). Short metro strands (such as
  Ashburn–McLean) are local builds under $15K. The blended average cost
  of an access circuit is **about $15K per month**. Distance enters only
  through tails and metro builds, consistent with the rule that backbone
  mileage is never a cost.

### Consequence

Facilities dominate (on the order of $6.2M per year, against roughly
$180K per year for a circuit) and backbone geography is free. The design
therefore minimizes the number of accredited facilities and favors
co-location and reuse over greenfield builds — the economic backing for
the intentional-cluster aggregation tier above.
