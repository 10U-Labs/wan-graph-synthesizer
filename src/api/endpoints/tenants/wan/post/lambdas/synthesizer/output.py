"""Build the synthesis payload the REST API serves to the browser."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from synthesizer.codec import PROVIDER_KIND
from synthesizer.collections import site_role
from synthesizer.input_graph import Site, link_key
from synthesizer.model import Synthesis, SynthesisArtifacts, SourceFiles, is_carrier_pop
from synthesizer.validation import included_site_ids


def sorted_fiber_segments(synthesis: Synthesis) -> list[tuple[str, str]]:
    """Return the synthesis's physical link keys in sorted order."""
    return sorted(synthesis.fiber_segment_keys)


def included_demand_count(sites: Iterable[Site], synthesis: Synthesis) -> int:
    """Count demand sites actually homed into the synthesis.

    Mirrors the synthesis-membership semantics of the backbone count: a demand site
    only counts once it is homed to a backbone node (i.e. it appears in
    :func:`included_site_ids`), not merely because it was loaded as demand.
    """
    included = included_site_ids(synthesis)
    return sum(
        1 for site in sites if not is_carrier_pop(site) and site.id in included
    )


def _demand_path_kind(source_site: Site) -> str:
    """Label a demand-to-backbone access link by its source site kind."""
    return "provider_to_backbone" if source_site.kind == PROVIDER_KIND else "tenant_to_backbone"


def synthesis_payload(sources: SourceFiles, artifacts: SynthesisArtifacts) -> dict[str, Any]:
    """Build the full synthesis, sites, links, and validation report as a dict.

    This is the single serialization the REST API slices into its atomic
    endpoints, so the frontend consumes one coherent synthesis computation.
    """
    sites = artifacts.sites
    fiber_segments = artifacts.fiber_segments
    synthesis = artifacts.synthesis
    validation = artifacts.validation
    sites_by_id = {site.id: site for site in sites}
    return {
        "sites_files": [str(path) for path in sources.site_files],
        "fiber_segment_file": str(sources.link_path),
        "objective": (
            "Two-tier WAN synthesis: demand sites (tenant sites and provider regions) home "
            "to a meshed backbone of selected Carrier PoPs over the physical Carrier "
            "graph, with at least three strong backbone nodes and extra ones added "
            "where they bring demand closer."
        ),
        "summary": {
            "backbone_count": len(synthesis.backbone_ids),
            "transit_count": len(synthesis.transit_ids),
            "demand_site_count": included_demand_count(sites, synthesis),
            "access_path_count": len(synthesis.access_paths),
            "fiber_segment_count": len(synthesis.fiber_segment_keys),
            "access_miles": round(synthesis.metrics.access_miles, 3),
            "physical_carrier_miles": round(synthesis.metrics.physical_miles, 3),
            # The fewest fiber miles any backbone meeting this tenant's requirements could
            # have run (see :mod:`synthesizer.survivable`). It sits beside the miles the
            # synthesis actually ordered because the two are only meaningful together: a
            # figure for what was bought says nothing about whether it was worth buying
            # until there is a figure for what the same requirements could have cost.
            "backbone_lower_bound_miles": round(
                synthesis.metrics.backbone_lower_bound_miles, 3
            ),
            "total_synthesis_miles": round(
                synthesis.metrics.access_miles + synthesis.metrics.physical_miles, 3
            ),
            "score": round(synthesis.metrics.score, 3),
            "backbone_nodes": [
                sites_by_id[site_id].name for site_id in synthesis.backbone_ids
            ],
        },
        "validation": validation,
        "sites": [
            {
                **asdict(site),
                "tier_role": site_role(site, synthesis),
                "included": site.id in included_site_ids(synthesis),
            }
            for site in sites
        ],
        "access_paths": [
            {
                "source_id": link.source,
                "source_name": sites_by_id[link.source].name,
                "target_id": link.target,
                "target_name": sites_by_id[link.target].name,
                "link_kind": _demand_path_kind(sites_by_id[link.source]),
                "distance_miles": round(link.distance_miles, 3),
            }
            for link in sorted(synthesis.access_paths, key=lambda item: (item.source, item.target))
        ],
        "fiber_segments": [
            {
                "source_id": left,
                "source_name": sites_by_id[left].name,
                "target_id": right,
                "target_name": sites_by_id[right].name,
                "link_kind": "carrier_physical",
                "distance_miles": round(fiber_segments[link_key(left, right)].distance_miles, 3),
                "source_page": fiber_segments[link_key(left, right)].source_page,
                "note": fiber_segments[link_key(left, right)].note,
            }
            for left, right in sorted_fiber_segments(synthesis)
        ],
        "path_uses": [
            {
                "purpose": path_use.purpose,
                "source_id": path_use.source,
                "source_name": sites_by_id[path_use.source].name,
                "target_id": path_use.target,
                "target_name": sites_by_id[path_use.target].name,
                "distance_miles": round(path_use.distance_miles, 3),
                "carrier": path_use.carrier,
                "path": [sites_by_id[site_id].name for site_id in path_use.path],
                "reason": path_use.reason,
                "requested_by": [
                    sites_by_id[site_id].name for site_id in path_use.requested_by
                ],
            }
            for path_use in synthesis.path_uses
        ],
    }
