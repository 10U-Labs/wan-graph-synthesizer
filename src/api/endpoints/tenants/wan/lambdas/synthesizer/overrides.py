"""Resolve operator role pins into search role overrides.

The synthesizer's search consumes a :class:`~synthesizer.model.RoleOverrides`
describing which PoPs are forced backbone nodes, which are barred from the
backbone, and how the operator's forced edges resolve to ids. This module builds
that object from the operator's force-pins (resolved by name), gated by the set of
data-center cities a colocation provider operates in. It runs before the search
and never calls back into it.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet

from synthesizer.input_graph import PhysicalEdge, Vertex, edge_key
from synthesizer.model import (
    DesignParams,
    ForcedConnection,
    ForcedLinks,
    RoleOverrides,
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
    forced_backbone: set[str],
    prohibited_backbone: AbstractSet[str] = frozenset(),
) -> None:
    """Reject contradictory backbone pins.

    A PoP cannot be both forced onto and prohibited from the backbone tier.
    """
    clash = forced_backbone & prohibited_backbone
    if clash:
        raise ValueError(
            "PoPs cannot be both forced onto and prohibited from the backbone tier: "
            f"{sorted(clash)}"
        )


def _reject_non_datacenter_pins(
    forced_backbone: set[str],
    carrier_pops: list[Vertex],
    datacenter_cities: frozenset[tuple[str, str]],
) -> None:
    """Raise for any forced backbone pin whose city is not a data-center city.

    The data-center gate is absolute: a carrier PoP may serve as a backbone node only
    where a colocation provider has a cage, and an operator force does not lift the
    constraint. A forced pin at a non-data-center city is rejected by name.
    """
    pop_by_id = {pop.id: pop for pop in carrier_pops}
    for backbone_id in sorted(forced_backbone):
        pop = pop_by_id[backbone_id]
        if (pop.info.municipality, pop.info.state) not in datacenter_cities:
            raise ValueError(
                f"forced backbone PoP is not at a data-center city: {pop.name}"
            )


def _resolve_operator_pins(
    vertices: list[Vertex],
    params: DesignParams,
) -> tuple[set[str], set[str]]:
    """Resolve operator backbone pins, gated by the data-center cities.

    Returns the forced-backbone and prohibited-backbone id sets. A forced pin at a
    city no colocation provider serves is rejected -- the data-center gate applies to
    operator forces too.
    """
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    name_to_id = pop_id_by_name(carrier_pops)
    forced_backbone = resolve_pinned_ids(
        params.forced_backbone_names, name_to_id, "forced_backbone"
    )
    prohibited_backbone = resolve_pinned_ids(
        params.exclusions.prohibited_backbone_names, name_to_id, "prohibited_backbone"
    )
    reject_override_conflicts(forced_backbone, prohibited_backbone)
    if params.restrict_backbone_to_datacenters:
        _reject_non_datacenter_pins(forced_backbone, carrier_pops, params.datacenter_cities)
    return forced_backbone, prohibited_backbone


def _forced_backbone_endpoint(
    name: str, name_to_id: dict[str, str], forced_backbone: set[str]
) -> str:
    """Resolve a forced-connection backbone endpoint, requiring it be a forced node."""
    if name not in name_to_id:
        raise ValueError(f"forced-connection backbone not found in the Carrier graph: {name}")
    backbone_id = name_to_id[name]
    if backbone_id not in forced_backbone:
        raise ValueError(f"forced-connection endpoint must be a forced backbone node: {name}")
    return backbone_id


def _backbone_backbone_pair(
    connection: ForcedConnection, name_to_id: dict[str, str], forced_backbone: set[str]
) -> tuple[str, str]:
    """Resolve a backbone-backbone connection's endpoints to a forced-backbone edge key."""
    left = _forced_backbone_endpoint(connection.source, name_to_id, forced_backbone)
    right = _forced_backbone_endpoint(connection.target, name_to_id, forced_backbone)
    return edge_key(left, right)


def _excluded_backbone_endpoint(name: str, name_to_id: dict[str, str]) -> str:
    """Resolve an excluded backbone-backbone endpoint, requiring only a carrier PoP."""
    if name not in name_to_id:
        raise ValueError(f"excluded-connection backbone not found in the Carrier graph: {name}")
    return name_to_id[name]


def _removed_backbone_pair(
    connection: ForcedConnection, name_to_id: dict[str, str]
) -> tuple[str, str]:
    """Resolve an excluded backbone-backbone connection's endpoints to an edge key."""
    left = _excluded_backbone_endpoint(connection.source, name_to_id)
    right = _excluded_backbone_endpoint(connection.target, name_to_id)
    return edge_key(left, right)


def _removed_backbone_links(
    connections: tuple[ForcedConnection, ...],
    name_to_id: dict[str, str],
) -> frozenset[tuple[str, str]]:
    """Resolve operator-pruned backbone-backbone pairs to edge keys.

    Each endpoint need only be a carrier PoP (an unknown name raises a ``ValueError``);
    the pair is pruned only when the synthesizer seats both as backbone nodes, otherwise
    it is a no-op. Pinning the endpoints as forced backbone nodes is not required.
    """
    return frozenset(
        _removed_backbone_pair(connection, name_to_id) for connection in connections
    )


def resolve_forced_links(
    connections: tuple[ForcedConnection, ...],
    vertices: list[Vertex],
    forced_backbone: set[str],
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> ForcedLinks:
    """Resolve operator forced/pruned connections to id-typed link sets, validating tiers.

    Returns a :class:`ForcedLinks` of the backbone-backbone and access-backbone links,
    plus the ``removed_backbone`` pairs the operator pruned from the mesh. Each forced
    endpoint must already be seated in the tier its edge type requires, or a
    ``ValueError`` names the offending connection; a pruned ``removed_backbone``
    endpoint need only be a carrier PoP.
    """
    name_to_id = pop_id_by_name([vertex for vertex in vertices if is_carrier_pop(vertex)])
    access_name_to_id = {
        vertex.name: vertex.id for vertex in vertices if not is_carrier_pop(vertex)
    }
    backbone_links: set[tuple[str, str]] = set()
    access_links: set[tuple[str, str]] = set()
    for connection in connections:
        if connection.edge_type == "backbone-backbone":
            backbone_links.add(
                _backbone_backbone_pair(connection, name_to_id, forced_backbone)
            )
        else:  # access-backbone
            if connection.source not in access_name_to_id:
                raise ValueError(f"forced-connection access node not found: {connection.source}")
            backbone = _forced_backbone_endpoint(
                connection.target, name_to_id, forced_backbone
            )
            access_links.add((access_name_to_id[connection.source], backbone))
    return ForcedLinks(
        backbone=frozenset(backbone_links),
        access=frozenset(access_links),
        removed_backbone=_removed_backbone_links(excluded_connections, name_to_id),
    )


def apply_role_overrides(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    forced_connections: tuple[ForcedConnection, ...] = (),
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], RoleOverrides]:
    """Resolve operator pins into the search's role overrides.

    Operator forced backbone nodes stay required; ``forced_connections`` are resolved
    to id-typed link sets against the seated backbone, and ``excluded_connections`` to
    the backbone-backbone pairs pruned from the mesh.
    ``params.exclusions.prohibited_backbone_names`` are barred from the backbone tier
    and land in ``RoleOverrides.prohibited_backbone_ids``. Forced backbone pins are
    gated by ``params.datacenter_cities``: a pin at a city no colocation provider
    serves is rejected. The graph is returned unchanged (operator pins resolve to
    existing carrier-PoP ids; demand attachment is the caller's earlier stage).
    """
    forced_backbone, prohibited_backbone = _resolve_operator_pins(vertices, params)
    overrides = RoleOverrides(
        forced_backbone_ids=frozenset(forced_backbone),
        prohibited_backbone_ids=frozenset(prohibited_backbone),
        forced_links=resolve_forced_links(
            forced_connections, vertices, forced_backbone, excluded_connections
        ),
    )
    return vertices, physical_edges, overrides
