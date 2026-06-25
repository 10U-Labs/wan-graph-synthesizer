"""Apply operator-forced connections during the routing stage.

The overrides layer resolves the operator's forced connections into a
:class:`~synthesizer.model.ForcedLinks` bundle; these helpers consume it while
the synthesizer routes a design, so the pinned edges are honored:
backbone-backbone pairs pruned from the mesh and access-backbone links pinned as
homes. They depend only on the model, so the synthesizer imports them without a
cycle.
"""

from __future__ import annotations

from synthesizer.input_graph import Vertex, haversine_miles
from synthesizer.model import ForcedLinks


def removed_backbone_pairs(
    backbone_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    """Operator-pruned backbone pairs whose both endpoints are in the current backbone."""
    return frozenset(
        pair
        for pair in links.removed_backbone
        if pair[0] in backbone_set and pair[1] in backbone_set
    )


def apply_forced_access_homes(
    access: Vertex,
    completed: list[str],
    links: ForcedLinks,
    pop_by_id: dict[str, Vertex],
    homes: int,
) -> list[str]:
    """Pin operator-forced backbone nodes into a demand vertex's homes.

    Each backbone node the operator forced this demand vertex onto leads, then the
    nearest of its computed homes fill any remaining slot, capped at ``homes``. With
    no forced link the homes are returned unchanged.
    """
    required = [backbone for acc, backbone in sorted(links.access) if acc == access.id]
    if not required:
        return completed
    nearest = sorted(
        (home for home in completed if home not in required),
        key=lambda home: haversine_miles(access, pop_by_id[home]),
    )
    return (required + nearest)[:homes]
