"""The synthesizer's input-graph types and primitive helpers.

The vertex/edge dataclasses and geographic helpers that describe the graph the
synthesizer designs against: a :class:`Vertex` is an access site, cloud region, or
carrier PoP; a :class:`PhysicalEdge` is fiber between two PoPs.
:mod:`synthesizer.codec` builds these from the stored JSON rows. The
synthesizer's own design vocabulary -- tiers, tuning, validation -- lives in
``synthesizer.model``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class VertexInfo:
    """Descriptive, non-structural attributes of a vertex.

    ``description`` is free-text source provenance; ``municipality`` and ``state``
    are the serving city and 2-letter U.S. state shown in the map tooltip (carrier
    PoPs derive these from their ``City, ST`` name).
    """

    description: str = ""
    municipality: str = ""
    state: str = ""

@dataclass(frozen=True)
class Vertex:
    """A geographic vertex: an access site, a cloud region, or a carrier PoP.

    ``kind`` is the facility type derived from the endpoint the place was sent to
    (``PoP`` for carriers, ``CSP data center`` for cloud regions, an access kind for
    tenant sites and off-net candidates). Carrier PoPs are the vertices whose ``kind``
    marks them as routable backbone nodes (see ``synthesizer.model.is_carrier_pop``);
    everything else is an access/demand vertex. Who *owns* a place is the tenant the WAN
    is being built for -- known from the endpoint path -- so it is not stored per vertex.
    """

    id: str
    name: str
    kind: str
    coords: tuple[float, float]  # (latitude, longitude)
    # Descriptive (non-structural) attributes: source notes plus the serving
    # municipality and 2-letter state shown in the map tooltip.
    info: VertexInfo = field(default_factory=VertexInfo)
    # Whether the vertex appears on the source mapbook layer (carrier PoPs are
    # backbone infrastructure and are not shown; installations and regions are).
    shown_in_map: bool = True

    @property
    def lat(self) -> float:
        """Latitude in degrees."""
        return self.coords[0]

    @property
    def lon(self) -> float:
        """Longitude in degrees."""
        return self.coords[1]

@dataclass(frozen=True)
class PhysicalEdge:
    """A physical Carrier mapbook link between two PoPs."""

    source: str
    target: str
    distance_miles: float
    source_page: str = ""
    note: str = ""

def edge_key(left: str, right: str) -> tuple[str, str]:
    """Return the two PoP ids as an order-independent edge key."""
    if left == right:
        raise ValueError(f"Self-loop is not a valid Carrier edge: {left}")
    return (left, right) if left < right else (right, left)

def haversine_miles(a: Vertex, b: Vertex) -> float:
    """Great-circle distance between two vertices in miles."""
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)
    sin_lat = math.sin(delta_lat / 2.0)
    sin_lon = math.sin(delta_lon / 2.0)
    value = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))
