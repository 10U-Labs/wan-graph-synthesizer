"""Apply operator-forced paths during the routing stage.

``synthesizer.overrides`` resolves the operator's forced paths into a
:class:`~synthesizer.model.ForcedLinks` bundle; these helpers consume it while
the synthesizer draws a synthesis, so the pinned links are honored: backbone-backbone
pairs forced into or pruned from the mesh, and access-backbone links pinned as homes.
They depend only on the model, so the synthesizer imports them without a cycle.
"""

from __future__ import annotations

from synthesizer.input_graph import Site, haversine_miles
from synthesizer.model import ForcedLinks


def _pairs_within(
    backbone_set: set[str], pairs: frozenset[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    """The pairs whose both endpoints are in the current backbone set."""
    return frozenset(
        pair for pair in pairs if pair[0] in backbone_set and pair[1] in backbone_set
    )


def removed_backbone_pairs(
    backbone_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    """Operator-pruned backbone pairs whose both endpoints are in the current backbone."""
    return _pairs_within(backbone_set, links.removed_backbone)


def forced_backbone_pairs(
    backbone_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    """Operator-forced backbone pairs whose both endpoints are in the current backbone.

    A candidate backbone set that seats only one endpoint cannot carry the link, so the
    pin simply does not apply there; the forced-backbone pins are what guarantee both
    endpoints are seated in the synthesis that wins.
    """
    return _pairs_within(backbone_set, links.backbone)


def apply_forced_access_homes(
    access: Site,
    completed: list[str],
    links: ForcedLinks,
    pop_by_id: dict[str, Site],
    homes: int,
) -> list[str]:
    """Pin operator-forced backbone nodes into a demand site's homes.

    Each backbone node the operator forced this demand site onto leads, then the
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
