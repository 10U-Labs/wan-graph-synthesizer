from __future__ import annotations

from dataclasses import dataclass

from synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LOCAL_FIBER_RADIUS_MILES,
    LocalFiberTwinSettings,
    build_local_fiber_twin,
    unique_twin_id,
)
from synthesizer.model import is_carrier_pop
from synthesizer.input_graph import FiberSegment, Site

OFF_NET_ID_PREFIX = "offnet_"
OFF_NET_LINK_NOTE = "synthetic off-net local-fiber link"


@dataclass(frozen=True)
class SeatedOffNetSites:
    sites: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    seat_ids: frozenset[str]


def realize_off_net_sites(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    off_net_roster: list[Site],
    forced_names: frozenset[str],
) -> SeatedOffNetSites:
    carrier_pops = [site for site in sites if is_carrier_pop(site)]
    carrier_names = {pop.name for pop in carrier_pops}
    used_ids = {site.id for site in sites}
    augmented_sites = list(sites)
    augmented_links = dict(fiber_segments)
    seat_ids: set[str] = set()
    for site in sorted(off_net_roster, key=lambda site: site.id):
        if site.name not in forced_names:
            continue
        if site.name in carrier_names:
            raise ValueError(
                f"forced off-net site is already a carrier PoP: {site.name}"
            )
        twin_id = unique_twin_id(f"{OFF_NET_ID_PREFIX}{site.id}", used_ids)
        built = build_local_fiber_twin(
            site, twin_id, carrier_pops,
            LocalFiberTwinSettings(note=OFF_NET_LINK_NOTE),
        )
        if built is None:
            raise ValueError(
                f"off-net site {site.name} has fewer than {LOCAL_FIBER_MIN_LINKS} "
                f"carrier PoPs within {LOCAL_FIBER_RADIUS_MILES:.0f} mi; cannot seat it"
            )
        used_ids.add(twin_id)
        augmented_sites.append(built[0])
        augmented_links.update(built[1])
        seat_ids.add(twin_id)
    return SeatedOffNetSites(augmented_sites, augmented_links, frozenset(seat_ids))
