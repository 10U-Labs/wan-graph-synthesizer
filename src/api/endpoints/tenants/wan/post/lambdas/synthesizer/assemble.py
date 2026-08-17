"""Assemble a complete two-tier design for one fixed set of backbone PoPs.

Everything here answers the same question: given these backbone nodes, what design do they
make, and do they make one at all. Nothing here chooses the backbone nodes -- the search
that does that (:mod:`synthesizer.synthesize`) and the coverage growth that adds to them
(:mod:`synthesizer.coverage`) both stand above this module and both call into it.

Keeping it separate is what lets those two be separate. The growth step has to build a
design to judge a candidate, and the search has to grow the backbone once it has a base, so
if the builder lived with either one the other would have to import it and the two would
point at each other.
"""

from __future__ import annotations

from dataclasses import dataclass

from synthesizer.input_graph import PhysicalEdge, Vertex, haversine_miles
from synthesizer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    PathUse,
)
from synthesizer.forced import (
    apply_forced_access_homes,
    forced_backbone_pairs,
    removed_backbone_pairs,
)
from synthesizer.graphs import path_edge_keys
from synthesizer.backbone import BackboneConstraints, backbone_mesh_paths
from synthesizer.ceiling import BackupRouteLimit
from synthesizer.search_plan import _SearchPlan


@dataclass
class _DesignDraft:
    access_edges: list[AccessEdge]
    path_uses: list[PathUse]


def finalize_design(
    backbone_ids: tuple[str, ...],
    draft: _DesignDraft,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> Design:
    """Compute edge sets, mileage estimate, and score for a design draft."""
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        physical_edges[key].distance_miles for key in physical_edge_keys
    )
    score = access_miles + physical_miles
    carrier_on_paths = {vertex_id for use in draft.path_uses for vertex_id in use.path}
    transit_ids = tuple(sorted(carrier_on_paths - set(backbone_ids)))
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_edges=draft.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=draft.path_uses,
        metrics=DesignMetrics(score, access_miles, physical_miles),
    )


def nearest_pop_id(access: Vertex, carrier_pops: list[Vertex]) -> str:
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id


def assign_access(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> list[AccessEdge] | None:
    """Home every demand vertex to its nearest backbone nodes in a single pass.

    Each demand vertex (a unified tenant site or provider region) homes to its
    ``plan.tuning.access_backbone_links`` nearest selected backbone nodes, ranked by
    great-circle distance, with any operator-forced access-backbone link leading its
    homes regardless of distance. The same code path serves tenant and provider demand --
    they differ only by source kind at output time. Returns the access edges, or None
    when the backbone is smaller than the configured number of homes (no vertex could
    reach that many distinct nodes).
    """
    links = plan.tuning.access_backbone_links
    backbone_set = set(backbone_ids)
    if len(backbone_set) < links:
        return None
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    access_edges: list[AccessEdge] = []
    for access in inputs.access_vertices:
        completed = [
            backbone_id
            for _distance, backbone_id in sorted(
                (haversine_miles(access, pop_by_id[backbone_id]), backbone_id)
                for backbone_id in backbone_set
            )
        ][:links]
        completed = apply_forced_access_homes(
            access, completed, plan.forced_links, pop_by_id, links
        )
        access_edges.extend(
            AccessEdge(
                access.id, backbone_id,
                haversine_miles(access, pop_by_id[backbone_id]),
            )
            for backbone_id in completed
        )
    return access_edges


def backbone_physically_biconnectable(
    backbone_ids: tuple[str, ...], inputs: DesignInputs
) -> bool:
    """True if the backbone nodes can be wired into a city-survivable physical-fiber mesh.

    They can iff they all share one common biconnected block of the carrier graph --
    otherwise some single city separates two of them and no routing survives its loss.
    Being city-survivable implies cable-survivable, so this subsumes the old 2-edge gate.
    """
    common: frozenset[int] | None = None
    for node in backbone_ids:
        blocks = inputs.carrier_blocks.get(node, frozenset())
        common = blocks if common is None else common & blocks
    return common is not None and bool(common)


def forced_backbone_resilience_error(
    required: frozenset[str], inputs: DesignInputs, min_count: int
) -> str | None:
    """Why the operator's forced backbone nodes can never form a resilient design, or None.

    A forced node behind a single carrier city (sharing no block with the other forced
    nodes, or sitting in no cyclic block at all) makes every candidate set fail the
    physical gate, so the search would end with an opaque "no feasible design". Caught up
    front, this names the offending nodes so the operator can fix ``etc/*.yml`` -- the
    reject rule wins over the force.
    """
    if not required:
        return None
    blocks_by_id = inputs.carrier_blocks
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    names = ", ".join(sorted(pop_by_id[node].name for node in required))
    common = blocks_by_id.get(next(iter(required)), frozenset())
    for node in required:
        common &= blocks_by_id.get(node, frozenset())
    if not common:
        return (
            "Forced backbone nodes share no common biconnected block of the carrier fiber "
            f"graph, so no design can survive a single city loss: {names}"
        )
    best = max(
        sum(
            1
            for node in inputs.eligible_backbone_ids
            if block in blocks_by_id.get(node, frozenset())
        )
        for block in common
    )
    if best < min_count:
        return (
            "A forced backbone node sits in a carrier fiber pocket too small for a "
            f"{min_count}-node biconnected backbone: {names}"
        )
    return None


def evaluate_backbone(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> list[AccessEdge] | None:
    """Score a backbone set's feasibility and demand homing without routing paths.

    Returns None when the backbone nodes cannot be wired into a city-survivable physical-
    fiber mesh (a single city loss would strand one -- which also rules out a node that
    cannot reach its peers, since biconnectivity implies they are all mutually reachable),
    or the backbone is smaller than the configured number of homes per demand vertex (so
    ``assign_access`` cannot give each demand vertex that many distinct backbone nodes).
    Routed paths are deferred to the winning set, since they do not affect the ranking.
    """
    if not backbone_physically_biconnectable(backbone_ids, inputs):
        return None
    return assign_access(backbone_ids, inputs, plan)


def routed_path_uses(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> list[PathUse]:
    """Reconstruct the backbone-mesh paths for a design."""
    backbone_set = set(backbone_ids)
    constraints = BackboneConstraints(
        removed_backbone_pairs(backbone_set, plan.forced_links),
        number_of_diverse_paths=plan.tuning.backbone_number_of_diverse_paths,
        forced_pairs=forced_backbone_pairs(backbone_set, plan.forced_links),
        limit=BackupRouteLimit(
            plan.tuning.backbone_max_backup_route_multiple, inputs.all_distances
        ),
        seat_cap=plan.seat_cap,
    )
    return backbone_mesh_paths(
        backbone_ids, inputs.all_distances, inputs.all_predecessors, physical_edges, constraints
    )


def build_design_for_backbone(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> Design | None:
    """Assemble a full two-tier design for one fixed set of backbone PoPs.

    Returns None if a backbone node cannot reach enough peers to wire its mesh links, or
    the backbone is too small to give each demand vertex its configured number of homes.
    """
    access_edges = evaluate_backbone(backbone_ids, inputs, plan)
    if access_edges is None:
        return None
    path_uses = routed_path_uses(backbone_ids, inputs, plan, inputs.physical_edges)
    draft = _DesignDraft(access_edges, path_uses)
    return finalize_design(backbone_ids, draft, inputs.physical_edges)
