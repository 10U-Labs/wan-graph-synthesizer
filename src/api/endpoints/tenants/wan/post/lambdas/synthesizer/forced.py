from __future__ import annotations

from synthesizer.input_graph import Site, haversine_miles
from synthesizer.model import ForcedLinks


def _pairs_within(
    backbone_set: set[str], pairs: frozenset[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    return frozenset(
        pair for pair in pairs if pair[0] in backbone_set and pair[1] in backbone_set
    )


def removed_backbone_pairs(
    backbone_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    return _pairs_within(backbone_set, links.removed_backbone)


def forced_backbone_pairs(
    backbone_set: set[str], links: ForcedLinks
) -> frozenset[tuple[str, str]]:
    return _pairs_within(backbone_set, links.backbone)


def apply_forced_access_homes(
    access: Site,
    completed: list[str],
    links: ForcedLinks,
    pop_by_id: dict[str, Site],
    homes: int,
) -> list[str]:
    required = [backbone for acc, backbone in sorted(links.access) if acc == access.id]
    if not required:
        return completed
    nearest = sorted(
        (home for home in completed if home not in required),
        key=lambda home: haversine_miles(access, pop_by_id[home]),
    )
    return (required + nearest)[:homes]
