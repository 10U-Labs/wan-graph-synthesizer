"""Frozen plan dataclasses shared across the core-set search.

These carry the per-run context every candidate core set reuses: the aggregations a
design may seat (operator pins plus the optional co-located twins), the access-vertex
clusters, and the assembled search plan. They hold data only -- the search logic that
builds and consumes them lives in :mod:`wan_designer.optimize`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from wan_graph.model import ForcedLinks, Tuning, Vertex


@dataclass(frozen=True)
class _AggregationPlan:
    """The aggregations a design may seat.

    ``operator_forced`` are the operator's pinned aggregations, always seated. A
    forced installation's co-located twin is one of these, so installations enter
    the aggregation tier only by operator force; an operator pin may, however, also
    win a core slot. The remaining fields carry the optional co-located twins the
    search may seat so a core also serves as an aggregation: each twin id to its
    core, each core's reach-around set,
    and the twin vertices whose coordinates (their core's) drive access homing.
    """

    operator_forced: frozenset[str] = frozenset()
    twin_to_core: dict[str, str] = field(default_factory=dict)
    reach_avoiding: dict[str, set[str]] = field(default_factory=dict)
    twin_vertices: dict[str, Vertex] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterPlan:
    """Access-vertex clusters plus the radius bounding each cluster's head locality.

    The clusters come from density-clustering the access vertices once (geography is
    core-independent); ``radius`` is the scale at which they cohere, used to keep a
    cluster's head genuinely nearby (see :func:`wan_designer.optimize.cluster_local_heads`).
    """

    clusters: list[list[str]] = field(default_factory=list)
    radius: float = math.inf


@dataclass(frozen=True)
class _SearchPlan:
    """Pre-computed context shared across every candidate core set.

    ``cluster_plan`` holds the access-vertex clusters (each cluster's heads are
    chosen relative to its own extent) and their locality radius.
    ``feasibility_cache`` memoizes vertex-disjoint homing reachability per
    (aggregation, core set, homing degree) so the search avoids re-running max-flows.
    ``aggregations`` carries the operator pins and the optional core twins.
    """

    core_candidates: list[str]
    aggregations: _AggregationPlan
    strength_by_id: dict[str, float]
    cluster_plan: ClusterPlan = field(default_factory=ClusterPlan)
    feasibility_cache: dict[tuple[str, tuple[str, ...], int], bool] = field(
        default_factory=dict
    )
    tuning: Tuning = field(default_factory=Tuning)  # the dials this plan was built from
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

    @property
    def required_cores(self) -> frozenset[str]:
        """The operator-forced cores fixed into every candidate set."""
        return self.forced_links.required_cores
