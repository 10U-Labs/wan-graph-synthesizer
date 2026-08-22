from __future__ import annotations

import logging
from dataclasses import dataclass

from synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LocalFiberTwinSettings,
    build_local_fiber_twin,
    unique_twin_id,
)
from synthesizer.model import is_carrier_pop
from synthesizer.input_graph import FiberSegment, Site

logger = logging.getLogger(__name__)

ON_NET_ID_PREFIX = "fac_"
ON_NET_LINK_NOTE = "synthetic on-net fabrication backbone link"


@dataclass(frozen=True)
class FabricatedOnNetNodes:
    sites: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    on_net_ids: frozenset[str]


def _coord_key(site: Site) -> tuple[float, float]:
    return (round(site.lat, 4), round(site.lon, 4))


def fabricate_missing_on_net_nodes(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    forced_backbone_names: frozenset[str] = frozenset(),
) -> FabricatedOnNetNodes:
    carrier_pops = [site for site in sites if is_carrier_pop(site)]
    used_ids = {site.id for site in sites}
    augmented_sites = list(sites)
    augmented_links = dict(fiber_segments)
    on_net_ids: set[str] = set()
    seen_coords: set[tuple[float, float]] = set()
    for location in sorted(
        (
            site for site in sites
            if not is_carrier_pop(site) and site.name in forced_backbone_names
        ),
        key=lambda site: site.id,
    ):
        coord_key = _coord_key(location)
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)
        twin_id = unique_twin_id(f"{ON_NET_ID_PREFIX}{location.id}", used_ids)
        built = build_local_fiber_twin(
            location, twin_id, carrier_pops,
            LocalFiberTwinSettings(note=ON_NET_LINK_NOTE, max_radius=None),
        )
        if built is None:
            logger.info(
                "Location %s has fewer than %d carrier PoPs to wire to; "
                "leaving it demand-only",
                location.id,
                LOCAL_FIBER_MIN_LINKS,
            )
            continue
        used_ids.add(twin_id)
        augmented_sites.append(built[0])
        augmented_links.update(built[1])
        on_net_ids.add(twin_id)
    return FabricatedOnNetNodes(augmented_sites, augmented_links, frozenset(on_net_ids))
