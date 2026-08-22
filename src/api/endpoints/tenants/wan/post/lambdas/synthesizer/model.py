from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from synthesizer.input_graph import FiberSegment, Site


@dataclass(frozen=True)
class AccessPath:
    source: str
    target: str
    distance_miles: float

LINK_FOR_TARGET = "site_target"
LINK_FOR_PIN = "operator_pin"


@dataclass(frozen=True)
class SynthesisPath:
    purpose: str
    source: str
    target: str
    path: tuple[str, ...]
    distance_miles: float
    reason: str = LINK_FOR_TARGET
    requested_by: tuple[str, ...] = ()
    carrier: str = ""

@dataclass
class SynthesisMetrics:
    score: float
    access_miles: float
    physical_miles: float
    backbone_lower_bound_miles: float = 0.0

@dataclass
class Synthesis:
    backbone_ids: tuple[str, ...]
    transit_ids: tuple[str, ...]
    access_paths: list[AccessPath]
    fiber_segment_keys: set[tuple[str, str]]
    path_uses: list[SynthesisPath]
    metrics: SynthesisMetrics

@dataclass(frozen=True)
class SearchMemoryBudget:
    memory_share: float = 0.6
    bytes_per_combination: int = 160


@dataclass(frozen=True)
class Tuning:
    compass_sector_count: int = 8
    backbone_number_of_diverse_paths: int = 3
    backbone_coverage_target_miles: int = 600
    access_backbone_links: int = 2
    backbone_max_backup_path_multiple: float = 3.0
    search_memory_budget: SearchMemoryBudget = field(default_factory=SearchMemoryBudget)

@dataclass(frozen=True)
class NamedLink:
    source: str
    target: str

@dataclass(frozen=True)
class RoleExclusions:
    prohibited_backbone_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class SynthesisParams:
    min_backbone_count: int = 3
    max_backbone_count: int | None = None
    forced_backbone_names: tuple[str, ...] = ()
    degree_exempt_backbone_names: tuple[str, ...] = ()
    exclusions: RoleExclusions = field(default_factory=RoleExclusions)
    promote_high_degree_convergences: bool = True
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class OperatorLinks:
    backbone: tuple[NamedLink, ...] = ()
    access: tuple[NamedLink, ...] = ()
    removed_backbone: tuple[NamedLink, ...] = ()

@dataclass(frozen=True)
class ForcedLinks:
    backbone: frozenset[tuple[str, str]] = frozenset()
    access: frozenset[tuple[str, str]] = frozenset()
    removed_backbone: frozenset[tuple[str, str]] = frozenset()
    required_backbone: frozenset[str] = frozenset()

@dataclass(frozen=True)
class RoleOverrides:
    forced_backbone_ids: frozenset[str] = frozenset()
    prohibited_backbone_ids: frozenset[str] = frozenset()
    degree_exempt_backbone_ids: frozenset[str] = frozenset()
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

@dataclass(frozen=True)
class SynthesisInputs:
    access_sites: list[Site]
    carrier_pops: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    eligible_backbone_ids: set[str]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]
    carrier_blocks: dict[str, frozenset[int]]

@dataclass(frozen=True)
class MeshRequirements:
    number_of_diverse_paths: int = 3
    degree_exempt: frozenset[str] = frozenset()
    ceilings: Mapping[str, int] | None = None


class ValidationReport(TypedDict):
    connected: bool
    component_count: int
    min_distinct_neighbor_degree: int
    degree_deficient_sites: list[dict[str, object]]
    biconnected_no_articulation_points: bool
    articulation_points: list[dict[str, str]]
    access_sites_with_required_backbone_links: bool
    demand_missing_backbone_redundancy: list[dict[str, str]]
    backbone_meets_mesh_link_target: bool
    backbone_diverse_paths_deficient: list[dict[str, object]]
    backbone_meets_independent_mesh_link_target: bool
    backbone_mesh_independence_deficient: list[dict[str, object]]
    backbone_degree_exempt: list[dict[str, str]]
    backbone_diverse_paths_ceilings: list[dict[str, object]]
    backbone_diverse_paths_ceiling_limited: list[dict[str, object]]
    backbone_diverse_paths_above_target: list[dict[str, object]]
    backbone_mesh_survives_any_one_link_loss: bool
    backbone_mesh_survives_any_one_site_loss: bool

@dataclass(frozen=True)
class InputFiles:
    site_files: tuple[tuple[str, Path], ...]
    link_path: Path
    regional_link_paths: tuple[Path, ...] = ()
    off_net_path: Path | None = None

@dataclass(frozen=True)
class SourceFiles:
    site_files: tuple[Path, ...]
    link_path: Path

@dataclass(frozen=True)
class SynthesisArtifacts:
    sites: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    synthesis: Synthesis
    validation: ValidationReport

KIND_POP = "PoP"
KIND_ROADM = "ROADM"
CARRIER_KINDS = frozenset({KIND_POP, KIND_ROADM})

def is_carrier_pop(site: Site) -> bool:
    return site.kind in CARRIER_KINDS
