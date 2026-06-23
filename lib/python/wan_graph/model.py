"""Shared interchange types and primitive helpers for the WAN graph.

The vertex/edge dataclasses and geographic helpers used on *both* sides of the JSON
interchange: the inputs script (which writes these shapes as JSON via
:mod:`wan_graph.codec`) and the synthesizer (which reads them back). The synthesizer's
own design vocabulary -- tiers, tuning, validation -- lives in ``wan_synthesizer.model``;
this module holds only what the two programs share.
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

    ``tenant`` is the operator or program the vertex belongs to (e.g. ``Lumen``,
    ``F-35``, ``AWS``, ``DCN``); ``kind`` is the facility type (``PoP``,
    ``ROADM``, ``Military installation``, ``CSP data center``, ``UARC``,
    ``Corporate office``). Carrier PoPs are the vertices whose ``kind`` marks them
    as routable backbone nodes (see ``wan_synthesizer.model.is_carrier_pop``);
    everything else is an access/demand vertex.
    """

    id: str
    name: str
    tenant: str
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
