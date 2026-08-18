"""Validate a design against the hard resilience requirements."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import combinations

from synthesizer.input_graph import Vertex, edge_key
from synthesizer.model import (
    LINK_FOR_TARGET,
    Design,
    DesignPath,
    MeshRequirements,
    ValidationReport,
)
from synthesizer.graphs import (
    articulation_points,
    connected_components,
    is_two_edge_connected,
    is_two_vertex_connected,
    path_edge_keys,
)


# Every backbone node must link to at least ``number_of_diverse_paths`` other backbone nodes --
# but only once the backbone is larger than that target, since fewer nodes cannot
# reach it.


def node_mesh_target(node: str, targets: MeshRequirements) -> int:
    """How many independent mesh links ``node`` owes: the tenant's degree, or its ceiling.

    A node cannot owe more links than its fiber can independently carry, so the target is
    the smaller of the operator's degree and the node's computed ceiling (see
    :mod:`synthesizer.ceiling`). Where the ground is the constraint the target comes down
    on its own, and no exemption list has to name the node.

    Lowering it can only relax: ``min`` never raises a target above what was asked, so no
    design that passes today is refused because of a number the tool derived. A node with
    no ceiling recorded owes the full degree, which covers both the caller with no substrate
    to hand and the node the substrate says nothing about.

    Which leaves the opposite risk, a ceiling below what the node could really hold, and
    with it a target lowered past a shortfall worth reporting. Unbounded, the ceiling could
    not do this: a set of links with pairwise disjoint failure cities is a feasible flow in
    the network it maximises over, so the flow can never come out under them. A ceiling
    measured against the operator's backup path multiple is a search among the paths that
    multiple allows rather than a maximum over all of them (see
    :func:`synthesizer.ceiling.independent_paths`), and no exact search is available at any
    price, so it can now sit one under. That it happened is not silent: a node the ceiling
    holds below the configured degree is reported by name in
    ``backbone_diverse_paths_ceiling_limited`` (see :func:`ceiling_limited_nodes`), which is
    where an operator sees a target the tool lowered rather than one they set.
    """
    ceilings = targets.ceilings
    if ceilings is None or node not in ceilings:
        return targets.number_of_diverse_paths
    return min(targets.number_of_diverse_paths, ceilings[node])


def backbone_mesh_deficient(
    backbone_ids: tuple[str, ...],
    backbone_degrees: dict[str, int],
    vertices_by_id: dict[str, Vertex],
    targets: MeshRequirements,
) -> list[dict[str, object]]:
    """Backbone nodes with fewer mesh links than their own target.

    With ``targets.number_of_diverse_paths`` or fewer backbone nodes the target cannot be
    met (a node has only that many peers), so the list is empty. That guard is unconditional, so a
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
    if len(backbone_ids) <= targets.number_of_diverse_paths:
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

def backbone_mesh_fiber_segments(design: Design) -> set[tuple[str, str]]:
    """The fiber segments the backbone mesh's paths actually run over.

    The union of every ``backbone_mesh`` path's fiber segments -- the real fiber, not the
    logical city-pairs, so two links sharing a corridor count that corridor once.
    """
    segments: set[tuple[str, str]] = set()
    for use in design.path_uses:
        if use.purpose == "backbone_mesh":
            segments |= path_edge_keys(use.path)
    return segments

def _backbone_mesh_survives(
    design: Design, is_resilient: Callable[[set[str], set[tuple[str, str]]], bool]
) -> bool:
    """Whether the fiber segments the backbone's paths run over pass ``is_resilient``.

    Shared by the fiber- and city-loss metrics: both judge the same union of fiber
    segments (the real fiber the mesh rides, not the logical pairs), differing only in the
    resilience test. A backbone of fewer than two nodes is trivially resilient; a backbone
    node whose paths run over no fiber segment reads as disconnected.
    """
    ids = set(design.backbone_ids)
    if len(ids) < 2:
        return True
    segments = backbone_mesh_fiber_segments(design)
    vertices = ids | {vertex for segment in segments for vertex in segment}
    return is_resilient(vertices, segments)

def backbone_mesh_two_edge_connected(design: Design) -> bool:
    """True if the backbone's fiber survives the loss of any single fiber segment."""
    return _backbone_mesh_survives(design, is_two_edge_connected)

def backbone_mesh_two_vertex_connected(design: Design) -> bool:
    """True if the backbone's physical fiber survives the loss of any single city.

    The city-loss analogue: the union of fiber segments must have no articulation point,
    so no single city -- a backbone city or a transit city the paths cross -- can split
    the backbone.
    """
    return _backbone_mesh_survives(design, is_two_vertex_connected)

def failure_cities_per_path(path_uses: list[DesignPath], node: str) -> list[frozenset[str]]:
    """Per mesh link at ``node`` in ``path_uses``, the cities whose loss would take it down.

    Every city the link's path crosses except ``node`` itself: a transit city, and the
    peer at the far end, which is a city too.

    Taking the paths rather than a whole design is what lets the mesh be measured while it
    is still being built, before there is a design to hand.
    """
    return [cities for _peer, cities in paths_out_of(path_uses, node)]


def paths_out_of(
    path_uses: list[DesignPath], node: str
) -> list[tuple[str, frozenset[str]]]:
    """Per mesh link at ``node``, the peer it reaches and the cities that would take it down.

    The peer travels beside the cities because the two answer different halves of one
    question. Two links that share a city normally fail together, so they are one way out of
    the site rather than two -- unless the city they share is the peer both of them end at,
    in which case they are two paths to one peer and the shared city is the destination
    itself. Losing it costs the site those paths and nothing else, which is what a way out
    is. Only :func:`diverse_path_count` needs to tell the two apart, and it cannot
    from the cities alone.
    """
    return [
        (
            use.target if use.source == node else use.source,
            frozenset(use.path) - {node},
        )
        for use in path_uses
        if use.purpose == "backbone_mesh" and node in (use.source, use.target)
    ]


def mesh_link_failure_cities(design: Design, node: str) -> list[frozenset[str]]:
    """Per mesh link at ``node``, the cities whose loss would take that link down."""
    return failure_cities_per_path(design.path_uses, node)


def _all_disjoint(links: tuple[tuple[str, frozenset[str]], ...]) -> bool:
    """Whether no two of these links would be taken down by the loss of one city.

    A city in two links' failure sets fails both, so the two are one way out of the site.
    The exception is the peer two links both end at: a site with one peer and two paths to
    it loses both when that peer goes, and has lost the destination rather than its
    protection. Those two are the two paths a two-site backbone is asked for, and charging
    them for the city they exist to reach would make the number unreachable.
    """
    for (near_peer, near), (far_peer, far) in combinations(links, 2):
        shared = near & far
        if near_peer == far_peer:
            shared -= {near_peer}
        if shared:
            return False
    return True


def diverse_path_count(path_uses: list[DesignPath], node: str) -> int:
    """How many of ``node``'s mesh links in ``path_uses`` no single city's loss takes two of.

    A node's nominal degree counts lines on a diagram. This counts links that fail
    independently, which is the number the configured degree is asking for: the largest
    set of the node's links no one city's loss takes two of (see :func:`_all_disjoint`,
    which is where two paths to one peer are told apart from two links through one transit
    city). Searched largest first over a handful of links, so the exhaustive walk stays
    cheap.

    It takes the paths rather than a whole design for the same reason
    :func:`failure_cities_per_path` does: the mesh is measured while it is still being
    built, before there is a design to hand. A caller holding one passes
    ``design.path_uses``.
    """
    links = paths_out_of(path_uses, node)
    for size in range(len(links), 0, -1):
        if any(_all_disjoint(combo) for combo in combinations(links, size)):
            return size
    return 0


def backbone_mesh_independence_deficient(
    design: Design,
    vertices_by_id: dict[str, Vertex],
    targets: MeshRequirements,
) -> list[dict[str, object]]:
    """Backbone nodes without their own target of independently failing mesh links.

    The city-diversity counterpart of :func:`backbone_mesh_deficient`: a node can hold its
    full nominal degree and still fall below it when one transit city goes, because two of
    its links cross that city.

    Every backbone is asked, however few sites are in it. A backbone with fewer peers than
    paths asked for used to be waved through here, on the reasoning that a site cannot hold
    more paths than it has peers to reach -- which stopped being true when a peer on a
    backbone whose config caps its seats that low was allowed to carry more than one path
    (see :func:`synthesizer.ceiling.paths_per_peer`).
    Two-Node is the backbone that reasoning waved through: two sites asking for two paths,
    published with five paths between them and never once measured (GitHub issue #58). A
    site whose fiber genuinely cannot carry the number is still not reported, because its
    ceiling brings its own target down (see :func:`node_mesh_target`).

    The target is per node (see :func:`node_mesh_target`), which is what separates a
    shortfall the ground imposes from a shortfall the tool caused. A node whose every path
    out crosses one of two cities is reported at neither -- two is all it could ever hold --
    while a node whose fiber supports the full degree is still reported when the mesh gives
    it less, because that one is a defect somebody can fix.

    A node in ``targets.degree_exempt`` is left out here too. A spur behind a single point
    of failure on the carrier's fiber is exactly the node that fails both counts, so an
    exemption that silenced only the nominal one would leave the operator with the same
    report they asked to be rid of -- and this is the count the build refuses on.
    """
    return [
        {
            "id": backbone_id,
            "name": vertices_by_id[backbone_id].name,
            "independent_degree": degree,
        }
        for backbone_id, degree in sorted(
            (node, diverse_path_count(design.path_uses, node)) for node in design.backbone_ids
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

    A node the substrate said nothing about has no ceiling and so never appears: the tool
    made no decision about it to report.
    """
    if ceilings is None:
        return []
    return [
        (node, ceilings[node])
        for node in sorted(backbone_ids)
        if node in ceilings and keep(ceilings[node])
    ]


def diverse_path_ceilings_reported(
    backbone_ids: tuple[str, ...],
    vertices_by_id: dict[str, Vertex],
    targets: MeshRequirements,
) -> list[dict[str, object]]:
    """Every backbone node's computed ceiling beside the target it was held to.

    :func:`ceiling_limited_nodes` reports only the nodes the ceiling lowered, which is what
    an operator needs to see and not enough for a reader outside the build to check the
    lowering. The two numbers together are what say a node short of its target was short of
    a link its fiber could have carried, rather than of one the backup path multiple
    forbids -- and the second of those is not a defect anybody can close.

    A node the substrate said nothing about has no ceiling and so never appears here either;
    it owes the full configured degree and the tool decided nothing about it to report.
    """
    return [
        {
            "id": node,
            "name": vertices_by_id[node].name,
            "ceiling": ceiling,
            "target": node_mesh_target(node, targets),
        }
        for node, ceiling in _ceilings_where(
            backbone_ids, targets.ceilings, lambda _ceiling: True
        )
    ]


def ceiling_limited_nodes(
    backbone_ids: tuple[str, ...],
    vertices_by_id: dict[str, Vertex],
    targets: MeshRequirements,
) -> list[dict[str, object]]:
    """Backbone nodes the tool held to less than the tenant degree, and to what.

    A ceiling is only as good as the substrate behind it: a fiber path missing from the
    inputs lowers a node's ceiling, which lowers its target, which could let a design pass
    that should not. So every reduction the tool made on its own is named here rather than
    left to be inferred from a link count -- an operator reads what was asked of each node,
    beside the exemptions they asked for themselves.
    """
    return [
        {"id": node, "name": vertices_by_id[node].name, "ceiling": ceiling}
        for node, ceiling in _ceilings_where(
            backbone_ids, targets.ceilings, lambda value: value < targets.number_of_diverse_paths
        )
    ]


def node_mesh_links(design: Design, node: str) -> list[DesignPath]:
    """Every drawn backbone mesh link with ``node`` at one end."""
    return [
        use
        for use in design.path_uses
        if use.purpose == "backbone_mesh" and node in (use.source, use.target)
    ]


def unrequested_mesh_links(design: Design, node: str) -> list[dict[str, object]]:
    """The mesh links at ``node`` that ``node`` did not reach for, each with why it is there.

    A link the node picked itself is one of the number its tenant asked for -- selection
    never gives a node more of those than its target. Every other link at the node is one
    somebody else's requirement put there, and the link carries which (see
    :data:`synthesizer.model.LINK_FOR_TARGET` and its siblings).

    A link the far end reached for is reported as the peer's rather than as a target, since
    from this node's side that is what it is: a link has two ends and only one of them
    asked for it.
    """
    unrequested: list[dict[str, object]] = [
        {
            "peer": use.target if use.source == node else use.source,
            "reason": "peer_target" if use.reason == LINK_FOR_TARGET else use.reason,
        }
        for use in node_mesh_links(design, node)
        if not (use.reason == LINK_FOR_TARGET and node in use.requested_by)
    ]
    return sorted(unrequested, key=lambda item: (str(item["peer"]), str(item["reason"])))


def above_target_nodes(
    design: Design,
    vertices_by_id: dict[str, Vertex],
    targets: MeshRequirements,
) -> list[dict[str, object]]:
    """Backbone nodes holding more links than they were asked for, and why each one stands.

    The number of diverse paths is the number a site gets, not a floor it may be carried
    past because the ground was generous (see
    :func:`synthesizer.backbone.select_backbone_mesh_pairs`). So a node above its target is
    the exception rather than the norm, and every link taking it there is attributable to
    somebody else's requirement: an operator pin, a peer that needed this node to reach its
    own target, a link holding the backbone together as one network, or a detour keeping
    one city off the only path.

    Reporting the reason is the point. A count alone leaves an operator to work out for
    themselves why the network they were handed is larger than the one they asked for, and
    the honest answer -- that each of these was unavoidable, and which requirement made it
    so -- is exactly what a count cannot say.

    The number compared against is the one the tenant asked for, not the per-node target
    :func:`node_mesh_target` lowers where the fiber cannot carry it. A node the ceiling
    holds to two still reaches for the tenant's three and may take a link through a single
    point of failure to get there; that link is one it asked for, and reporting it as
    surplus would tell an
    operator they were given fiber they ordered themselves. What is reported is fiber
    nobody ordered, which is a different question from how much protection came of it --
    so ``diverse_path_count`` sits beside ``link_count`` rather than standing in for it.

    Every node listed has at least one link it did not reach for, because selection never
    gives a node more of its own than the number asked, so the reasons below are never an
    empty list.
    """
    # The tenant's number flat. It once came down to the peers a site had to reach, since a
    # site could take only one path to each; a site whose config allows too few seats for
    # the paths it asks for now doubles up on a peer instead (see
    # :func:`synthesizer.ceiling.paths_per_peer`), so the paths it is entitled to are the
    # number asked for wherever they end.
    asked_for = targets.number_of_diverse_paths
    rows: list[dict[str, object]] = []
    for node in sorted(design.backbone_ids):
        links = node_mesh_links(design, node)
        if len(links) <= asked_for:
            continue
        rows.append({
            "id": node,
            "name": vertices_by_id[node].name,
            "target": asked_for,
            "link_count": len(links),
            "diverse_path_count": diverse_path_count(design.path_uses, node),
            "unrequested_links": unrequested_mesh_links(design, node),
        })
    return rows


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
    targets: MeshRequirements = MeshRequirements(),
) -> ValidationReport:
    """Check a design against every hard structural requirement.

    ``access_backbone_links`` is the exact number of backbone nodes each demand vertex
    must home to, the operator's configured access redundancy.

    ``targets`` says how many mesh links each backbone node owes (see
    :class:`synthesizer.model.MeshRequirements`): the operator's degree, the nodes it is not
    asked of, and each node's computed ceiling. The degree is therefore a per-node target
    rather than one number every node is held to -- a node is asked for the smaller of the
    degree and what its fiber can independently carry.

    Three things about that are reported rather than left to be inferred: the nodes the
    number was not asked of, the nodes whose target the tool lowered on its own, and the
    nodes holding more links than they were asked for, with what put each one there. All on
    one principle -- a check that was silenced, a number the tool chose for itself, or a
    path nobody ordered is something an operator reads, because a design that differs
    from the one that was asked for and does not say so is worse than the noise it saves.
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
        "backbone_diverse_paths_deficient": mesh_deficient,
        "backbone_meets_independent_mesh_link_target": not independence_deficient,
        "backbone_mesh_independence_deficient": independence_deficient,
        "backbone_degree_exempt": [
            {"id": backbone_id, "name": vertices_by_id[backbone_id].name}
            for backbone_id in sorted(set(design.backbone_ids) & targets.degree_exempt)
        ],
        "backbone_diverse_paths_ceilings": diverse_path_ceilings_reported(
            design.backbone_ids, vertices_by_id, targets
        ),
        "backbone_diverse_paths_ceiling_limited": ceiling_limited_nodes(
            design.backbone_ids, vertices_by_id, targets
        ),
        "backbone_diverse_paths_above_target": above_target_nodes(
            design, vertices_by_id, targets
        ),
        "backbone_mesh_two_edge_connected": backbone_mesh_two_edge_connected(design),
        "backbone_mesh_two_vertex_connected": backbone_mesh_two_vertex_connected(design),
    }
