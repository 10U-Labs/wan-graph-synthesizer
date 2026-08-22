from __future__ import annotations

from dataclasses import dataclass

from synthesizer.input_graph import (
    FiberSegment,
    Site,
    link_key,
    haversine_miles,
)
from synthesizer.model import KIND_POP

LOCAL_FIBER_LINKS = 3
LOCAL_FIBER_MIN_LINKS = 2
LOCAL_FIBER_RADIUS_MILES = 300.0


@dataclass(frozen=True)
class LocalFiberTwinSettings:
    note: str
    max_radius: float | None = LOCAL_FIBER_RADIUS_MILES


def nearest_carrier_pops(
    site: Site, carrier_pops: list[Site], links: int, max_radius: float | None
) -> list[Site]:
    ranked = sorted(
        ((haversine_miles(site, pop), pop) for pop in carrier_pops),
        key=lambda item: (item[0], item[1].id),
    )
    return [
        pop
        for distance, pop in ranked[:links]
        if max_radius is None or distance <= max_radius
    ]


def unique_twin_id(base: str, used_ids: set[str]) -> str:
    site_id = base
    suffix = 2
    while site_id in used_ids:
        site_id = f"{base}_{suffix}"
        suffix += 1
    return site_id


def build_local_fiber_twin(
    site: Site,
    twin_id: str,
    carrier_pops: list[Site],
    settings: LocalFiberTwinSettings,
) -> tuple[Site, dict[tuple[str, str], FiberSegment]] | None:
    neighbors = nearest_carrier_pops(
        site, carrier_pops, LOCAL_FIBER_LINKS, settings.max_radius
    )
    if len(neighbors) < LOCAL_FIBER_MIN_LINKS:
        return None
    twin = Site(
        id=twin_id,
        name=site.name,
        kind=KIND_POP,
        coords=site.coords,
        info=site.info,
    )
    links: dict[tuple[str, str], FiberSegment] = {}
    for pop in neighbors:
        key = link_key(twin.id, pop.id)
        links[key] = FiberSegment(
            source=key[0],
            target=key[1],
            distance_miles=haversine_miles(twin, pop),
            note=settings.note,
        )
    return twin, links
