"""The synthesizer's input-graph types and primitive helpers.

The site/link dataclasses and geographic helpers that describe the graph the
synthesizer syntheses against: a :class:`Site` is an access site, cloud region, or
carrier PoP; a :class:`FiberSegment` is fiber between two PoPs.
:mod:`synthesizer.codec` builds these from the stored JSON rows. The
synthesizer's own synthesis vocabulary -- tiers, tuning, validation -- lives in
``synthesizer.model``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class SiteInfo:
    """Descriptive, non-structural attributes of a site.

    ``description`` is free-text source provenance; ``municipality`` is the serving
    city, ``state`` its region/province (a 2-letter code for US and Canadian places,
    blank elsewhere), and ``country`` the nation. The map tooltip shows ``City, State``
    for US places and ``City, Country`` for everywhere else.
    """

    description: str = ""
    municipality: str = ""
    state: str = ""
    country: str = ""

@dataclass(frozen=True)
class Site:
    """A geographic site: an access site, a cloud region, or a carrier PoP.

    ``kind`` is the facility type derived from the endpoint the place was sent to
    (``PoP`` for carriers, ``provider region`` for provider regions, an access kind for
    tenant sites and off-net candidates). Carrier PoPs are the sites whose ``kind``
    marks them as routable backbone nodes (see ``synthesizer.model.is_carrier_pop``);
    everything else is an access/demand site. Who *owns* a place is the tenant the WAN
    is being built for -- known from the endpoint path -- so it is not stored per site.
    """

    id: str
    name: str
    kind: str
    coords: tuple[float, float]  # (latitude, longitude)
    # Descriptive (non-structural) attributes: source notes plus the serving
    # municipality, region/state and country shown in the map tooltip.
    info: SiteInfo = field(default_factory=SiteInfo)
    # A demand site the operator has marked OCONUS: it is dropped from the backbone
    # coverage-distance stop condition (it may sit farther than the target from every
    # backbone node), but still homes to its nearest node like any other site.
    exempt_from_distance_constraint: bool = False

    @property
    def lat(self) -> float:
        """Latitude in degrees."""
        return self.coords[0]

    @property
    def lon(self) -> float:
        """Longitude in degrees."""
        return self.coords[1]

@dataclass(frozen=True)
class FiberSegment:
    """A physical Carrier mapbook link between two PoPs.

    ``carriers`` are the carriers that have fiber between these two cities. A path is
    ordered from one carrier, so it may run over this segment only if that carrier is in
    here. An empty set is fiber no carrier sells -- the synthetic local fiber
    :func:`synthesizer.local_fiber.build_local_fiber_twin` lays from a fabricated twin to
    its nearest carrier PoPs is a lateral the operator builds themselves -- so it
    constrains nothing and any carrier's path may run over it.
    """

    source: str
    target: str
    distance_miles: float
    source_page: str = ""
    note: str = ""
    carriers: frozenset[str] = frozenset()

def link_key(left: str, right: str) -> tuple[str, str]:
    """Return the two PoP ids as an order-independent link key."""
    if left == right:
        raise ValueError(f"Self-loop is not a valid Carrier link: {left}")
    return (left, right) if left < right else (right, left)

def carriers_along(
    path: tuple[str, ...], fiber_segments: dict[tuple[str, str], FiberSegment]
) -> frozenset[str]:
    """The carriers that could sell every length of fiber along a path.

    A path is one thing an operator orders, from one carrier, so it is only real if some
    carrier has all of it. The answer is the carriers common to every segment the path
    crosses; the segments no carrier owns are skipped, since local fiber rules nobody out.
    An empty answer is a path nobody can sell.
    """
    common: frozenset[str] | None = None
    for index in range(len(path) - 1):
        owners = fiber_segments[link_key(path[index], path[index + 1])].carriers
        if not owners:
            continue
        common = owners if common is None else common & owners
    return common if common is not None else frozenset()

def haversine_miles(a: Site, b: Site) -> float:
    """Great-circle distance between two sites in miles."""
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)
    sin_lat = math.sin(delta_lat / 2.0)
    sin_lon = math.sin(delta_lon / 2.0)
    value = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))
