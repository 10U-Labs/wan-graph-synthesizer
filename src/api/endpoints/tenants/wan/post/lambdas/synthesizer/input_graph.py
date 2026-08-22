from __future__ import annotations

import math
from dataclasses import dataclass, field


EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class SiteInfo:
    description: str = ""
    municipality: str = ""
    state: str = ""
    country: str = ""

@dataclass(frozen=True)
class Site:
    id: str
    name: str
    kind: str
    coords: tuple[float, float]
    info: SiteInfo = field(default_factory=SiteInfo)
    exempt_from_distance_constraint: bool = False

    @property
    def lat(self) -> float:
        return self.coords[0]

    @property
    def lon(self) -> float:
        return self.coords[1]

@dataclass(frozen=True)
class FiberSegment:
    source: str
    target: str
    distance_miles: float
    source_page: str = ""
    note: str = ""
    carriers: frozenset[str] = frozenset()
    submarine: bool = False

def link_key(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError(f"Self-loop is not a valid Carrier link: {left}")
    return (left, right) if left < right else (right, left)

def carriers_along(
    path: tuple[str, ...], fiber_segments: dict[tuple[str, str], FiberSegment]
) -> frozenset[str]:
    common: frozenset[str] | None = None
    for index in range(len(path) - 1):
        owners = fiber_segments[link_key(path[index], path[index + 1])].carriers
        if not owners:
            continue
        common = owners if common is None else common & owners
    return common if common is not None else frozenset()

def haversine_miles(a: Site, b: Site) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)
    sin_lat = math.sin(delta_lat / 2.0)
    sin_lon = math.sin(delta_lon / 2.0)
    value = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))
