"""Frozen plan dataclass shared across the backbone-set search.

This carries the per-run context every candidate backbone set reuses: the strength
ranking, the disjoint-homing feasibility cache, the tuning dials, and the operator's
resolved forced links. It holds data only -- the search logic that builds and
consumes it lives in :mod:`synthesizer.synthesize`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from synthesizer.model import ForcedLinks, Tuning


@dataclass(frozen=True)
class _SearchPlan:
    """Pre-computed context shared across every candidate backbone set.

    ``backbone_candidates`` are the eligible PoPs ranked by strength.
    ``feasibility_cache`` memoizes vertex-disjoint homing reachability per
    (demand vertex, backbone set, homing degree) so the search avoids re-running
    max-flows. ``forced_links`` carries the operator's resolved pins for routing.
    """

    backbone_candidates: list[str]
    strength_by_id: dict[str, float]
    feasibility_cache: dict[tuple[str, tuple[str, ...], int], bool] = field(
        default_factory=dict
    )
    tuning: Tuning = field(default_factory=Tuning)  # the dials this plan was built from
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

    @property
    def required_backbone(self) -> frozenset[str]:
        """The operator-forced backbone nodes fixed into every candidate set."""
        return self.forced_links.required_backbone
