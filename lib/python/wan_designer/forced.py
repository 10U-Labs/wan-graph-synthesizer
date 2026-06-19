"""Apply operator-forced connections during the routing stage.

The overrides layer resolves the operator's forced connections into a
:class:`~wan_designer.model.ForcedLinks` bundle; these helpers consume it while
the optimizer routes a design, so the pinned edges are honored: core-core pairs
pruned from the backbone, aggregation-core links forced as routing sinks, and
access-aggregation links pinned as homes. They depend only on the model, so the
optimizer imports them without a cycle.
"""

from __future__ import annotations

from wan_designer.model import ForcedLinks, Vertex, haversine_miles


def removed_core_pairs(
    core_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    """Operator-pruned core-core pairs whose both endpoints are in the current core set."""
    return frozenset(
        pair
        for pair in links.removed_core
        if pair[0] in core_set and pair[1] in core_set
    )


def forced_cores_for_aggregation(
    aggregation_id: str, core_set: set[str], links: ForcedLinks
) -> frozenset[str]:
    """Forced cores this aggregation must home to, within the current core set."""
    return frozenset(
        core_id
        for agg_id, core_id in links.aggregation
        if agg_id == aggregation_id and core_id in core_set
    )


def apply_forced_access_homes(
    access: Vertex,
    completed: list[str],
    links: ForcedLinks,
    pop_by_id: dict[str, Vertex],
) -> list[str]:
    """Pin operator-forced aggregations into an access vertex's two homes.

    Each aggregation the operator forced this access node onto leads, then the
    nearest of its computed homes fill any remaining slot, capped at two. With no
    forced link the homes are returned unchanged.
    """
    required = [agg for acc, agg in sorted(links.access) if acc == access.id]
    if not required:
        return completed
    nearest = sorted(
        (home for home in completed if home not in required),
        key=lambda home: haversine_miles(access, pop_by_id[home]),
    )
    return (required + nearest)[:2]
