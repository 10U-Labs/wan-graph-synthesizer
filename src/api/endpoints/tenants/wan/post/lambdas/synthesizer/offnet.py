"""Seat operator-forced off-net locations as local-fiber-attached carrier twins.

An off-net seat is an operator location that is not itself a carrier PoP -- it has
no backbone fiber of its own -- but that the operator wants seated as a backbone
node. Its coordinates come from a dedicated off-net CSV and never enter the main
site pool, so it carries no access demand. When the operator force-pins such a seat
we stand up a carrier-PoP twin at its coordinates, wired by synthetic local fiber to
the nearest carrier PoPs (see :mod:`synthesizer.local_fiber`) -- the same mechanism
that backs forced installations.

Only forced off-net sites are realized; an unlisted site is ignored. Failure modes
are hard errors rather than silent skips, because the operator explicitly demanded
the seat: a site whose city is not a data-center city (the backbone gate is
absolute), a site that cannot reach two distinct carrier PoPs within range (it cannot
biconnect into the backbone), and a site whose name collides with a real carrier PoP
(the pin would be ambiguous).
"""

from __future__ import annotations

from dataclasses import dataclass

from synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LOCAL_FIBER_RADIUS_MILES,
    LocalFiberTwinSettings,
    build_local_fiber_twin,
    unique_twin_id,
)
from synthesizer.model import backbone_city_allowed, is_carrier_pop
from synthesizer.input_graph import FiberSegment, Site

OFF_NET_ID_PREFIX = "offnet_"
OFF_NET_LINK_NOTE = "synthetic off-net local-fiber link"


@dataclass(frozen=True)
class SeatedOffNetSites:
    """Off-net seats realized into the graph as local-fiber-attached carrier twins.

    ``sites`` and ``fiber_segments`` are the graph augmented with one twin PoP per
    forced off-net seat and its synthetic local-fiber links; ``seat_ids`` are those
    twins' ids. Each twin is resolved onto the operator's force-pin downstream.
    """

    sites: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    seat_ids: frozenset[str]


def realize_off_net_sites(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    sites: list[Site],
    forced_names: frozenset[str],
    datacenter_cities: frozenset[tuple[str, str]] | None = frozenset(),
) -> SeatedOffNetSites:
    """Seat a local-fiber twin for every off-net site the operator has force-pinned.

    ``forced_names`` is the operator's forced backbone names. A site whose name is not
    forced is ignored. A forced site whose name is also a carrier PoP raises
    ``ValueError``: the roster exists to offer seats where no carrier point is, so such
    a row is a place the seat cannot be built, and the pin it names resolves onto two
    sites. A forced site whose city
    is not in ``datacenter_cities`` raises ``ValueError`` (the backbone gate is
    absolute); when ``datacenter_cities`` is ``None`` (free-for-all) the gate is lifted.
    A forced site that cannot reach
    :data:`~synthesizer.local_fiber.LOCAL_FIBER_MIN_LINKS` carrier PoPs within range
    raises ``ValueError``.
    """
    carrier_pops = [site for site in sites if is_carrier_pop(site)]
    carrier_names = {pop.name for pop in carrier_pops}
    used_ids = {site.id for site in sites}
    augmented_sites = list(sites)
    augmented_links = dict(fiber_segments)
    seat_ids: set[str] = set()
    for site in sorted(sites, key=lambda site: site.id):
        if site.name not in forced_names:
            continue
        if site.name in carrier_names:
            raise ValueError(
                f"forced off-net site is already a carrier PoP: {site.name}"
            )
        if not backbone_city_allowed(site.info, datacenter_cities):
            raise ValueError(
                f"forced off-net site is not at a data-center city: {site.name}"
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
        # ``built`` is (twin site, its local-fiber links) -- index in to keep the
        # locals here under pylint's ceiling.
        used_ids.add(twin_id)
        augmented_sites.append(built[0])
        augmented_links.update(built[1])
        seat_ids.add(twin_id)
    return SeatedOffNetSites(augmented_sites, augmented_links, frozenset(seat_ids))
