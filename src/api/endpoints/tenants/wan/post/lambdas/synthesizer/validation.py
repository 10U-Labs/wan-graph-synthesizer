"""Validate a design against the hard resilience requirements."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import combinations

from synthesizer.input_graph import Vertex, edge_key
from synthesizer.model import Design, MeshTargets, ValidationReport
from synthesizer.graphs import (
    articulation_points,
    connected_components,
    is_two_edge_connected,
    is_two_vertex_connected,
    path_edge_keys,
)


# Every backbone node must link to at least ``mesh_degree`` other backbone nodes --
# but only once the backbone is larger than that target, since fewer nodes cannot
# reach it.


def node_mesh_target(node: str, targets: MeshTargets) -> int:
    """How many independent mesh links ``node`` owes: the tenant's degree, or its ceiling.

    A node cannot owe more links than its fiber can independently carry, so the target is
    the smaller of the operator's degree and the node's computed ceiling (see
    :mod:`synthesizer.ceiling`). Where the ground is the constraint the target comes down
    on its own, and no exemption list has to name the node.

    Lowering it can only relax. The ceiling is an upper bound on
    :func:`independent_mesh_degree` -- a set of links with pairwise disjoint failure cities
    is a feasible flow in the network the ceiling maximises over -- so ``min`` never raises
    a target above what was asked before, and no design that passes today is refused
    because of a number the tool derived. A node with no ceiling recorded owes the full
    degree, which covers both the caller with no substrate to hand and the node the
    substrate says nothing about.
    """
    ceilings = targets.ceilings
    if ceilings is None or node not in ceilings:
        return targets.mesh_degree
    return min(targets.mesh_degree, ceilings[node])


def backbone_mesh_deficient(
    backbone_ids: tuple[str, ...],
    backbone_degrees: dict[str, int],
    vertices_by_id: dict[str, Vertex],
    targets: MeshTargets,
) -> list[dict[str, object]]:
    """Backbone nodes with fewer mesh links than their own target.

    With ``targets.mesh_degree`` or fewer backbone nodes the target cannot be met (a node
    has only that many peers), so the list is empty. That guard is unconditional, so a
    backbone no larger than the degree reports nothing whatever the ceilings say -- which
    keeps the ceiling a pure relaxation and never a new refusal.

    Each node is held to :func:`node_mesh_target` -- the tenant's degree capped by what its
    fiber can carry -- rather than to the degree flat. The nominal and independent counts
    use the same target on purpose: two counts disagreeing about what one node owes would
    make the report contradict itself.

    A node in ``targets.degree_exempt`` is left out: the operator has said the degree is
    not asked of it, and reporting a shortfall nobody intends to act on buries the ones
    that matter.
    """
    if len(backbone_ids) <= targets.mesh_degree:
        return []
    return [
        {"id": backbone_id, "name": vertices_by_id[backbone_id].name, "degree": degree}
        for backbone_id, degree in sorted(backbone_degrees.items())
        if degree < node_mesh_target(backbone_id, targets)
        and backbone_id not in targets.degree_exempt
    ]


def design_edge_set(design: Design) -> set[tuple[str, str]]:
    """All edges in the design: selected physical edges plus access edges."""
    edges = set(design.physical_edge_keys)
    edges.update(edge_key(edge.source, edge.target) for edge in design.access_edges)
    return edges

def included_vertex_ids(design: Design) -> set[str]:
    """Every vertex id that participates in the design."""
    ids = set(design.backbone_ids) | set(design.transit_ids)
    ids.update(vertex_id for edge in design.physical_edge_keys for vertex_id in edge)
    ids.update(edge.source for edge in design.access_edges)
    ids.update(edge.target for edge in design.access_edges)
    return ids

def demand_backbone_homes(design: Design) -> dict[str, set[str]]:
    """The distinct backbone nodes each demand vertex homes to, by access edges."""
    homes: dict[str, set[str]] = {}
    for edge in design.access_edges:
        homes.setdefault(edge.source, set()).add(edge.target)
    return homes

def demand_without_backbone_redundancy(design: Design, homes: int) -> list[str]:
    """Demand vertices homing to a number of distinct backbone nodes other than ``homes``.

    The requirement is exact, not a floor: every demand vertex homes to exactly ``homes``
    backbone nodes, so both too few and too many are flagged.
    """
    return [
        demand_id
        for demand_id, targets in sorted(demand_backbone_homes(design).items())
        if len(targets) != homes
    ]

def backbone_mesh_pairs(design: Design) -> set[tuple[str, str]]:
    """The logical backbone-to-backbone mesh links, one per ``backbone_mesh`` path use."""
    return {
        edge_key(use.source, use.target)
        for use in design.path_uses
        if use.purpose == "backbone_mesh"
    }

def backbone_mesh_physical_spans(design: Design) -> set[tuple[str, str]]:
    """The physical fiber spans the backbone mesh actually routes over.

    The union of every ``backbone_mesh`` path's spans -- the real cables, not the logical
    city-pairs, so two links sharing a corridor count that corridor once.
    """
    spans: set[tuple[str, str]] = set()
    for use in design.path_uses:
        if use.purpose == "backbone_mesh":
            spans |= path_edge_keys(use.path)
    return spans

def _backbone_mesh_survives(
    design: Design, is_resilient: Callable[[set[str], set[tuple[str, str]]], bool]
) -> bool:
    """Whether the backbone's routed physical spans pass ``is_resilient``.

    Shared by the cable- and city-loss metrics: both judge the same span union (the real
    cables the mesh rides, not the logical pairs), differing only in the resilience test.
    A backbone of fewer than two nodes is trivially resilient; a backbone node with no
    routed span reads as disconnected.
    """
    ids = set(design.backbone_ids)
    if len(ids) < 2:
        return True
    spans = backbone_mesh_physical_spans(design)
    vertices = ids | {vertex for span in spans for vertex in span}
    return is_resilient(vertices, spans)

def backbone_mesh_two_edge_connected(design: Design) -> bool:
    """True if the backbone's physical fiber survives the loss of any single cable span."""
    return _backbone_mesh_survives(design, is_two_edge_connected)

def backbone_mesh_two_vertex_connected(design: Design) -> bool:
    """True if the backbone's physical fiber survives the loss of any single city.

    The city-loss analogue: the routed span union must have no articulation point, so no
    single city -- a backbone city or a transit city the routes pass through -- can split
    the backbone.
    """
    return _backbone_mesh_survives(design, is_two_vertex_connected)

def mesh_link_failure_cities(design: Design, node: str) -> list[frozenset[str]]:
    """Per mesh link at ``node``, the cities whose loss would take that link down.

    Every city the link's routed path visits except ``node`` itself: a transit city, and
    the peer at the far end, which is a city too. Two routes for the same pair both carry
    that pair's peer, so a detour never reads as a second independent link to it.
    """
    return [
        frozenset(use.path) - {node}
        for use in design.path_uses
        if use.purpose == "backbone_mesh" and node in (use.source, use.target)
    ]


def _all_disjoint(failure_cities: tuple[frozenset[str], ...]) -> bool:
    """Whether no city appears in two of these links' failure sets."""
    seen: set[str] = set()
    for cities in failure_cities:
        if seen & cities:
            return False
        seen |= cities
    return True


def independent_mesh_degree(design: Design, node: str) -> int:
    """How many of ``node``'s mesh links no single city's loss can take two of.

    A node's nominal degree counts lines on a diagram. This counts links that fail
    independently, which is the number the configured degree is asking for: the largest
    set of the node's links whose failure cities are pairwise disjoint. Searched largest
    first over a handful of links, so the exhaustive walk stays cheap.
    """
    links = mesh_link_failure_cities(design, node)
    for size in range(len(links), 0, -1):
        if any(_all_disjoint(combo) for combo in combinations(links, size)):
            return size
    return 0


def backbone_mesh_independence_deficient(
    design: Design,
    vertices_by_id: dict[str, Vertex],
    targets: MeshTargets,
) -> list[dict[str, object]]:
    """Backbone nodes without their own target of independently failing mesh links.

    The city-diversity counterpart of :func:`backbone_mesh_deficient`: a node can hold its
    full nominal degree and still fall below it when one transit city goes, because two of
    its links cross that city. With ``targets.mesh_degree`` or fewer backbone nodes the
    target cannot be met at all, so the list is empty.

    The target is per node (see :func:`node_mesh_target`), which is what separates a
    shortfall the ground imposes from a shortfall the tool caused. A node whose every route
    out crosses one of two cities is reported at neither -- two is all it could ever hold --
    while a node whose fiber supports the full degree is still reported when the mesh gives
    it less, because that one is a defect somebody can fix.

    A node in ``targets.degree_exempt`` is left out here too. A spur behind a carrier
    chokepoint is exactly the node that fails both counts, so an exemption that silenced
    only the nominal one would leave the operator with the same report they asked to be rid
    of -- and this is the count the build refuses on.
    """
    if len(design.backbone_ids) <= targets.mesh_degree:
        return []
    return [
        {
            "id": backbone_id,
            "name": vertices_by_id[backbone_id].name,
            "independent_degree": degree,
        }
        for backbone_id, degree in sorted(
            (node, independent_mesh_degree(design, node)) for node in design.backbone_ids
        )
        if degree < node_mesh_target(backbone_id, targets)
        and backbone_id not in targets.degree_exempt
    ]


def _ceilings_where(
    backbone_ids: tuple[str, ...],
    ceilings: Mapping[str, int] | None,
    keep: Callable[[int], bool],
) -> list[tuple[str, int]]:
    """The ``(node, ceiling)`` pairs ``keep`` selects, in id order.

    Shared by the two report fields, which differ only in which side of the tenant degree
    a ceiling has to fall on. A node the substrate said nothing about has no ceiling and so
    appears in neither: the tool made no decision about it to report.
    """
    if ceilings is None:
        return []
    return [
        (node, ceilings[node])
        for node in sorted(backbone_ids)
        if node in ceilings and keep(ceilings[node])
    ]


def ceiling_limited_nodes(
    backbone_ids: tuple[str, ...],
    vertices_by_id: dict[str, Vertex],
    targets: MeshTargets,
) -> list[dict[str, object]]:
    """Backbone nodes the tool held to less than the tenant degree, and to what.

    A ceiling is only as good as the substrate behind it: a fiber route missing from the
    inputs lowers a node's ceiling, which lowers its target, which could let a design pass
    that should not. So every reduction the tool made on its own is named here rather than
    left to be inferred from a link count -- an operator reads what was asked of each node,
    beside the exemptions they asked for themselves.
    """
    return [
        {"id": node, "name": vertices_by_id[node].name, "ceiling": ceiling}
        for node, ceiling in _ceilings_where(
            backbone_ids, targets.ceilings, lambda value: value < targets.mesh_degree
        )
    ]


def above_floor_nodes(
    design: Design,
    vertices_by_id: dict[str, Vertex],
    targets: MeshTargets,
) -> list[dict[str, object]]:
    """Backbone nodes the tool reached past the tenant degree for, and what came of it.

    The mesh degree is a floor, so a node whose fiber carries more independent routes than
    the degree asks for is aimed at its ceiling instead (see
    :func:`synthesizer.backbone.select_backbone_mesh_pairs`). That is the tool's decision
    rather than the operator's, so it is reported with both numbers: the ceiling it aimed
    at, and the independent links it came away with. The two differ when the routing could
    not deliver what the substrate allowed, which is worth seeing.
    """
    return [
        {
            "id": node,
            "name": vertices_by_id[node].name,
            "ceiling": ceiling,
            "independent_degree": independent_mesh_degree(design, node),
        }
        for node, ceiling in _ceilings_where(
            design.backbone_ids, targets.ceilings, lambda value: value > targets.mesh_degree
        )
    ]


def neighbor_degrees(
    ids: set[str], edges: set[tuple[str, str]]
) -> dict[str, int]:
    """Distinct-neighbor degree of every included vertex in the design graph."""
    neighbors: dict[str, set[str]] = {vertex_id: set() for vertex_id in ids}
    for left, right in edges:
        if left in ids and right in ids:
            neighbors[left].add(right)
            neighbors[right].add(left)
    return {vertex_id: len(value) for vertex_id, value in neighbors.items()}

def validate_design(
    vertices: list[Vertex],
    design: Design,
    access_backbone_links: int = 2,
    targets: MeshTargets = MeshTargets(),
) -> ValidationReport:
    """Check a design against every hard structural requirement.

    ``access_backbone_links`` is the exact number of backbone nodes each demand vertex
    must home to, the operator's configured access redundancy.

    ``targets`` says how many mesh links each backbone node owes (see
    :class:`synthesizer.model.MeshTargets`): the operator's degree, the nodes it is not
    asked of, and each node's computed ceiling. The degree is therefore a per-node target
    rather than one number every node is held to -- a node is asked for the smaller of the
    degree and what its fiber can independently carry.

    Three things about that are reported rather than left to be inferred: the nodes the
    degree was not asked of, the nodes whose target the tool lowered on its own, and the
    nodes it reached past the degree for. All on one principle -- a check that was silenced
    or a number the tool chose for itself is something an operator reads, because a
    reduction nobody can see is worse than the noise it removed.
    """
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    ids = included_vertex_ids(design)
    edges = design_edge_set(design)
    components = connected_components(ids, edges)
    degrees = neighbor_degrees(ids, edges)
    articulations = articulation_points(ids, edges) if len(components) == 1 else set()
    missing_redundancy = demand_without_backbone_redundancy(design, access_backbone_links)
    backbone_degrees = neighbor_degrees(set(design.backbone_ids), backbone_mesh_pairs(design))
    mesh_deficient = backbone_mesh_deficient(
        design.backbone_ids, backbone_degrees, vertices_by_id, targets
    )
    independence_deficient = backbone_mesh_independence_deficient(
        design, vertices_by_id, targets
    )

    return {
        "connected": len(components) == 1,
        "component_count": len(components),
        "min_distinct_neighbor_degree": min(degrees.values()) if degrees else 0,
        "degree_deficient_vertices": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name, "degree": degree}
            for vertex_id, degree in sorted(degrees.items())
            if degree < 2
        ],
        "biconnected_no_articulation_points": len(components) == 1 and not articulations,
        "articulation_points": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in sorted(articulations)
        ],
        "access_vertices_with_required_backbone_links": not missing_redundancy,
        "demand_missing_backbone_redundancy": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in missing_redundancy
        ],
        "backbone_meets_mesh_link_target": not mesh_deficient,
        "backbone_mesh_degree_deficient": mesh_deficient,
        "backbone_meets_independent_mesh_link_target": not independence_deficient,
        "backbone_mesh_independence_deficient": independence_deficient,
        "backbone_degree_exempt": [
            {"id": backbone_id, "name": vertices_by_id[backbone_id].name}
            for backbone_id in sorted(set(design.backbone_ids) & targets.degree_exempt)
        ],
        "backbone_mesh_degree_ceiling_limited": ceiling_limited_nodes(
            design.backbone_ids, vertices_by_id, targets
        ),
        "backbone_mesh_degree_above_floor": above_floor_nodes(
            design, vertices_by_id, targets
        ),
        "backbone_mesh_two_edge_connected": backbone_mesh_two_edge_connected(design),
        "backbone_mesh_two_vertex_connected": backbone_mesh_two_vertex_connected(design),
    }
