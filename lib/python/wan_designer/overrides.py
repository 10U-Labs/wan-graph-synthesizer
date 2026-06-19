"""Resolve operator role pins and population anchors into search role overrides.

The optimizer's search consumes a :class:`~wan_designer.model.RoleOverrides`
describing which PoPs are forced cores, which aggregations must be seated, which
are excluded, and how the core and aggregation tiers are restricted. This module
builds that object from two independent sources -- the operator's force-pins
(resolved by name) and the realized population anchors -- and stands up the
co-located ``AGGR`` twin for any operator PoP pinned as both a core and an
aggregation. It runs before the search and never calls back into it.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet

from wan_designer.model import (
    Design,
    DesignParams,
    ForcedConnection,
    ForcedLinks,
    PhysicalEdge,
    RoleOverrides,
    Vertex,
    edge_key,
    is_carrier_pop,
)


def pop_id_by_name(carrier_pops: list[Vertex]) -> dict[str, str]:
    """Map each Carrier PoP's display name to its vertex id for pin resolution."""
    return {pop.name: pop.id for pop in carrier_pops}

def resolve_pinned_ids(
    names: tuple[str, ...], name_to_id: dict[str, str], label: str
) -> set[str]:
    """Resolve operator-supplied PoP names to ids, rejecting any unknown name.

    ``label`` is the config field the names came from; it names the offending field
    in the error so the operator knows which list to fix.
    """
    resolved: set[str] = set()
    for name in names:
        if name not in name_to_id:
            raise ValueError(f"{label} entry not found in the Carrier graph: {name}")
        resolved.add(name_to_id[name])
    return resolved

def reject_override_conflicts(
    forced_core: set[str],
    forced_aggregation: set[str],
    excluded: set[str],
    prohibited_aggregation: AbstractSet[str] = frozenset(),
) -> None:
    """Reject contradictory role pins.

    An excluded PoP cannot also be a forced core or aggregation, and a PoP cannot be
    both forced onto and prohibited from the aggregation tier. Prohibiting a forced
    *core* is allowed -- that is the core-yes/aggregation-no combination the knob exists
    for.
    """
    clash = excluded & (forced_core | forced_aggregation)
    if clash:
        raise ValueError(f"PoPs cannot be both excluded and forced: {sorted(clash)}")
    forced_and_prohibited = forced_aggregation & prohibited_aggregation
    if forced_and_prohibited:
        raise ValueError(
            "PoPs cannot be both forced onto and prohibited from the aggregation tier: "
            f"{sorted(forced_and_prohibited)}"
        )

def twin_vertex_id(core_id: str) -> str:
    """The id of the co-located ``AGGR`` twin that shares a core's facility."""
    return f"aggr_{core_id}"

def colocated_twin(core: Vertex) -> Vertex:
    """Build the co-located ``AGGR`` vertex that shares a core's coordinates."""
    return Vertex(
        id=twin_vertex_id(core.id),
        name=f"AGGR {core.name}",
        tenant=core.tenant,
        kind=core.kind,
        coords=core.coords,
        info=core.info,
        shown_in_map=core.shown_in_map,
    )

def colocation_edges(
    core_id: str, twin_id: str, physical_edges: dict[tuple[str, str], PhysicalEdge]
) -> dict[tuple[str, str], PhysicalEdge]:
    """Edges standing up a co-located ``AGGR`` stack beside its core.

    A zero-mile in-facility cross-connect joins the two distinct hardware stacks,
    and every one of the core's fiber handoffs is duplicated onto the aggregation
    so it reaches a remote core without traversing its own co-located core.
    """
    facility = edge_key(core_id, twin_id)
    new_edges: dict[tuple[str, str], PhysicalEdge] = {
        facility: PhysicalEdge(
            source=facility[0], target=facility[1], distance_miles=0.0,
            note="in-facility core/aggregation cross-connect",
        )
    }
    for (left, right), edge in physical_edges.items():
        neighbor = right if left == core_id else left if right == core_id else None
        if neighbor is None:
            continue
        handoff = edge_key(twin_id, neighbor)
        new_edges[handoff] = PhysicalEdge(
            source=handoff[0], target=handoff[1], distance_miles=edge.distance_miles,
            source_page=edge.source_page, note="co-located aggregation fiber handoff",
        )
    return new_edges

def split_colocated(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    colocated_ids: set[str],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """Split each co-located PoP into its core vertex and a co-located ``AGGR`` twin."""
    vertex_by_id = {vertex.id: vertex for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    twin_by_core: dict[str, str] = {}
    for core_id in sorted(colocated_ids):
        twin = colocated_twin(vertex_by_id[core_id])
        twin_by_core[core_id] = twin.id
        augmented_vertices.append(twin)
        augmented_edges.update(colocation_edges(core_id, twin.id, physical_edges))
    return augmented_vertices, augmented_edges, twin_by_core

def _resolve_operator_pins(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
) -> tuple[
    list[Vertex], dict[tuple[str, str], PhysicalEdge], set[str], set[str], set[str], set[str]
]:
    """Resolve operator pins and split any operator co-location.

    Returns the (possibly augmented) graph plus the forced-core, operator-forced
    aggregation, excluded, and prohibited-aggregation id sets. A PoP pinned as both a
    core and an aggregation is split into a ``CORE`` vertex and a ``AGGR`` twin, and it
    is the twin's id that lands in the operator-forced aggregations. Prohibited
    aggregations resolve to plain carrier-PoP ids (never co-located).
    """
    name_to_id = pop_id_by_name([vertex for vertex in vertices if is_carrier_pop(vertex)])
    forced_core = resolve_pinned_ids(params.forced_core_names, name_to_id, "forced_cores")
    forced_aggregation = resolve_pinned_ids(
        params.forced_aggregation_names, name_to_id, "forced_aggregations"
    )
    excluded = resolve_pinned_ids(params.exclusions.excluded_names, name_to_id, "excluded")
    prohibited = resolve_pinned_ids(
        params.exclusions.prohibited_aggregation_names, name_to_id, "prohibited_aggregations"
    )
    reject_override_conflicts(forced_core, forced_aggregation, excluded, prohibited)
    colocated = forced_core & forced_aggregation
    vertices, physical_edges, twin_by_core = split_colocated(vertices, physical_edges, colocated)
    operator_forced = (forced_aggregation - colocated) | set(twin_by_core.values())
    return vertices, physical_edges, forced_core, operator_forced, excluded, prohibited


def materialize_selected_colocation_twins(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    design: Design,
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Stand up the co-located ``AGGR`` twin for every core the search dual-roled.

    The optimizer may seat a core's twin as an aggregation without an operator pin;
    that twin's id rides in ``design.aggregation_ids`` but its vertex and fiber are
    not yet in the graph. Materialize each such twin -- skipping any already present
    (an operator co-location or a ``fac_`` installation twin) -- so validation, the
    physical-resilience augmenter, and the payload all see a real aggregation vertex
    with the cross-connect and duplicated handoffs that back its redundancy.
    """
    existing = {vertex.id for vertex in vertices}
    vertex_by_id = {vertex.id: vertex for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    aggregation_ids = set(design.aggregation_ids)
    for core_id in design.core_ids:
        twin_id = twin_vertex_id(core_id)
        if twin_id in aggregation_ids and twin_id not in existing:
            augmented_vertices.append(colocated_twin(vertex_by_id[core_id]))
            augmented_edges.update(colocation_edges(core_id, twin_id, physical_edges))
            existing.add(twin_id)
    return augmented_vertices, augmented_edges


def _forced_core_endpoint(
    name: str, name_to_id: dict[str, str], forced_core: set[str]
) -> str:
    """Resolve a forced-connection core endpoint, requiring it be a forced core."""
    if name not in name_to_id:
        raise ValueError(f"forced-connection core not found in the Carrier graph: {name}")
    core_id = name_to_id[name]
    if core_id not in forced_core:
        raise ValueError(f"forced-connection endpoint must be a forced core: {name}")
    return core_id


def _forced_aggregation_endpoint(
    name: str, name_to_id: dict[str, str], forced_core: set[str], operator_forced: set[str]
) -> str:
    """Resolve a forced-connection aggregation endpoint to its seated vertex id.

    A co-located PoP (a forced core also forced as an aggregation) is seated as its
    ``AGGR`` twin, so resolve to that twin id; the endpoint must be a forced
    aggregation either way.
    """
    if name not in name_to_id:
        raise ValueError(f"forced-connection aggregation not found in the Carrier graph: {name}")
    carrier_id = name_to_id[name]
    seated = twin_vertex_id(carrier_id) if carrier_id in forced_core else carrier_id
    if seated not in operator_forced:
        raise ValueError(f"forced-connection endpoint must be a forced aggregation: {name}")
    return seated


def _core_core_pair(
    connection: ForcedConnection, name_to_id: dict[str, str], forced_core: set[str]
) -> tuple[str, str]:
    """Resolve a core-core connection's two endpoints to a forced-core edge key."""
    left = _forced_core_endpoint(connection.source, name_to_id, forced_core)
    right = _forced_core_endpoint(connection.target, name_to_id, forced_core)
    return edge_key(left, right)


def _removed_core_links(
    connections: tuple[ForcedConnection, ...],
    name_to_id: dict[str, str],
    forced_core: set[str],
) -> frozenset[tuple[str, str]]:
    """Resolve operator-pruned core-core pairs to edge keys, validating both endpoints.

    Each endpoint must be a forced core (you can only prune a link between cores you
    pinned), so an off-tier endpoint raises a ``ValueError`` naming the connection.
    """
    return frozenset(
        _core_core_pair(connection, name_to_id, forced_core) for connection in connections
    )


def resolve_forced_links(
    connections: tuple[ForcedConnection, ...],
    vertices: list[Vertex],
    forced_core: set[str],
    operator_forced: set[str],
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> ForcedLinks:
    """Resolve operator forced/pruned connections to id-typed link sets, validating tiers.

    Returns a :class:`ForcedLinks` of the core-core, aggregation-core, and
    access-aggregation links, plus the ``removed_core`` pairs the operator pruned
    from the full mesh. Each endpoint must already be seated in the tier its edge
    type requires, or a ``ValueError`` names the offending connection.
    """
    name_to_id = pop_id_by_name([vertex for vertex in vertices if is_carrier_pop(vertex)])
    access_name_to_id = {
        vertex.name: vertex.id for vertex in vertices if not is_carrier_pop(vertex)
    }
    core_links: set[tuple[str, str]] = set()
    aggregation_links: set[tuple[str, str]] = set()
    access_links: set[tuple[str, str]] = set()
    for connection in connections:
        if connection.edge_type == "core-core":
            core_links.add(_core_core_pair(connection, name_to_id, forced_core))
        elif connection.edge_type == "aggregation-core":
            agg = _forced_aggregation_endpoint(
                connection.source, name_to_id, forced_core, operator_forced
            )
            core = _forced_core_endpoint(connection.target, name_to_id, forced_core)
            aggregation_links.add((agg, core))
        else:  # access-aggregation
            if connection.source not in access_name_to_id:
                raise ValueError(f"forced-connection access node not found: {connection.source}")
            agg = _forced_aggregation_endpoint(
                connection.target, name_to_id, forced_core, operator_forced
            )
            access_links.add((access_name_to_id[connection.source], agg))
    return ForcedLinks(
        core=frozenset(core_links),
        aggregation=frozenset(aggregation_links),
        access=frozenset(access_links),
        removed_core=_removed_core_links(excluded_connections, name_to_id, forced_core),
    )


def apply_role_overrides(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    forced_connections: tuple[ForcedConnection, ...] = (),
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], RoleOverrides]:
    """Resolve operator pins into the search's role overrides.

    Operator forced cores stay required and an operator co-location is split into a
    ``CORE``/``AGGR`` pair. A forced installation has already been realized as a
    co-located carrier twin, so its force-pin resolves onto that twin here and lands
    in the forced aggregations like any other operator pin. ``forced_connections``
    are resolved to id-typed link sets against the seated tiers, and
    ``excluded_connections`` to the core-core pairs pruned from the full mesh.
    ``params.exclusions.prohibited_aggregation_names`` are barred from the aggregation
    tier (yet stay core-eligible) and land in ``RoleOverrides.prohibited_aggregation_ids``.
    """
    vertices, physical_edges, forced_core, operator_forced, excluded, prohibited = (
        _resolve_operator_pins(vertices, physical_edges, params)
    )
    overrides = RoleOverrides(
        forced_core_ids=frozenset(forced_core),
        forced_aggregation_ids=frozenset(operator_forced),
        excluded_ids=frozenset(excluded),
        prohibited_aggregation_ids=frozenset(prohibited),
        forced_links=resolve_forced_links(
            forced_connections, vertices, forced_core, operator_forced, excluded_connections
        ),
    )
    return vertices, physical_edges, overrides
