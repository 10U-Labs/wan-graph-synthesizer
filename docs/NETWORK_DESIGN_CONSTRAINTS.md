# WAN Design Constraints

This document is the source of truth for the three-tier WAN design
problem the optimizer solves. It complements `CONSTRAINTS.md`, which
covers platform and tooling constraints rather than the network design.

## Source of truth

The carrier topology and node roles come from the Lumen Next-Gen
Optical Network Mapbook (`LumenNetworkMapbook25`, five pages). The
mapbook is authoritative for how PoPs connect to each other.

It is transcribed into two files:

- `data/carrier_edges.csv` — which PoPs are directly connected (edges).
- `data/carrier_pop_roles.csv` — each PoP's role: `aggregator` or
  `roadm`.

Demand sites come from the input KMZ. It contains the F-35
installations, the Sentinel program locations, and the cloud Secret
Regions.

### The mapbook has no distances

The mapbook draws routes as geographic lines that follow real
right-of-way, not straight lines, and it lists no mileage. There is no
direct line between PoPs. Straight-line (haversine) distance between
PoPs must not be used as a design objective or cost. Distance may be
used only for access tail circuits (a demand site to its aggregation
PoP), which are new builds rather than existing carrier routes.

## Hard constraints

A design is invalid unless all of the following hold.

1. Every access node dual-homes to exactly two aggregation points.
2. Every aggregation point dual-homes to two distinct core nodes over
   node-disjoint paths.
3. Core nodes form a full mesh: every pair of cores is connected over
   the carrier graph.
4. There are at least three core nodes. More cores are allowed when
   needed for feasibility, provided the full mesh still holds.
5. Only `aggregator` PoPs may serve as aggregation or core nodes.
   `roadm` PoPs are optical pass-through only and are never aggregation
   or core nodes.
6. Sentinel aggregation:
   - 165 sites aggregate toward Malmstrom AFB.
   - 165 sites aggregate toward Minot AFB.
   - 165 sites aggregate toward F.E. Warren AFB.

## Objective

Among all designs that satisfy the hard constraints, prefer the one
with the strongest core nodes. A PoP's strength has three parts,
weighted roughly equally:

- Reach: node degree, the number of PoPs it connects to directly.
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
  two distinct core nodes over node-disjoint paths, like any
  aggregation point.
- The 165 sites single-home to their base. The two-aggregation rule
  (hard constraint 1) does not apply to them.

This constraint is layered on after the strength-based, three-core
optimizer rewrite lands.
