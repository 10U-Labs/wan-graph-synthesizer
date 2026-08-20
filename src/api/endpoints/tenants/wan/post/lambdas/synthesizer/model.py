"""The synthesizer's synthesis vocabulary: tiers, tuning, routing, and validation.

These types build on the input-graph types in ``synthesizer.input_graph``
(``Site`` / ``FiberSegment`` and the geographic helpers); everything here is the
synthesizer's own in-memory representation, layered on top of them.

The synthesis is two tiers: a meshed ``backbone`` of selected carrier PoPs (each at a
data-center city) and the demand that homes into it. Demand is labelled ``tenant``
(tenant sites) or ``provider`` (provider regions); both home to the backbone identically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from synthesizer.input_graph import FiberSegment, Site


@dataclass(frozen=True)
class AccessPath:
    """A logical link from a demand site (tenant site or provider region) to a backbone PoP."""

    source: str
    target: str
    distance_miles: float

# Why a path between two backbone nodes is in the synthesis. A site is drawn with exactly the
# number of ways out its tenant asked for, so any path it holds beyond that number is one
# somebody else's requirement put there, and there are only two things that can have.
# Carrying the cause on the path is what lets the report name it rather than leave an
# operator to infer from a count why their network is larger than they asked for.
#
# There were five of these until GitHub issue #60. Three of them named the pass that added
# the path -- a join holding the backbone together, a detour around a city carrying the
# whole network, a second path to a peer already reached -- and those passes are gone: the
# fiber is now chosen for the whole synthesis at once (see :mod:`synthesizer.survivable`), so
# every path in a synthesis is one some site's own requirement produced or one the operator
# wrote down.
LINK_FOR_TARGET = "site_target"  # a site reached for it to meet its own target
LINK_FOR_PIN = "operator_pin"  # the operator wrote it into etc/*.yml


@dataclass(frozen=True)
class SynthesisPath:
    """One path the synthesis ordered, over the physical graph, and why it exists.

    ``reason`` is why a ``backbone_mesh`` link exists, one of the five constants above.
    ``requested_by`` names the sites that reached for it and is empty unless ``reason`` is
    ``LINK_FOR_TARGET`` -- a link has two ends, and which end asked for it is exactly what
    separates a site's own link from one it is holding for a peer.
    """

    purpose: str
    source: str
    target: str
    path: tuple[str, ...]
    distance_miles: float
    reason: str = LINK_FOR_TARGET
    requested_by: tuple[str, ...] = ()

@dataclass
class SynthesisMetrics:
    """Mileage totals and the synthesis score for a synthesis.

    ``backbone_lower_bound_miles`` is the fewest fiber miles any backbone meeting this
    tenant's requirements over this carrier fiber could have run, computed as the answer to
    the linear-programming relaxation the fiber was chosen by (see
    :mod:`synthesizer.survivable`). It is published beside ``physical_miles`` because a
    synthesis is only as good as the shortest synthesis there is, and until that number travels
    with the synthesis nobody reading it can say how close this one came. A synthesis assembled
    without a fiber choice behind it -- a fixture, a hand-built draft -- carries no floor
    and reads zero.
    """

    score: float
    access_miles: float
    physical_miles: float
    backbone_lower_bound_miles: float = 0.0

@dataclass
class Synthesis:
    """A complete two-tier synthesis: the backbone, the demand it carries, paths, metrics."""

    backbone_ids: tuple[str, ...]
    transit_ids: tuple[str, ...]
    access_paths: list[AccessPath]
    fiber_segment_keys: set[tuple[str, str]]
    path_uses: list[SynthesisPath]
    metrics: SynthesisMetrics

@dataclass(frozen=True)
class SearchMemoryBudget:
    """Memory budget governing how many backbone sets the search may enumerate."""

    memory_share: float = 0.6  # share of RAM the backbone enumeration may use
    bytes_per_combination: int = 160  # peak bytes one enumerated backbone set costs


@dataclass(frozen=True)
class Tuning:
    """Algorithm dials plus the required redundancy degrees and coverage target.

    The two degrees are operator requirements the synthesis must meet, each its own
    REST resource (``backbone-number-of-diverse-paths`` / ``access-homing-degree``) with no
    default at the config layer; the values here are construction fallbacks only.
    ``backbone_number_of_diverse_paths`` is how many other backbone nodes each backbone node
    links to on the mesh; ``access_backbone_links`` is how many backbone nodes each
    demand site homes to. ``backbone_coverage_target_miles`` is likewise required
    at the config layer (its field default here is a construction fallback only,
    kept because dataclass field ordering forces one); it lives in the ``knobs``
    resource rather than its own, since it describes the network an operator wants.
    ``backbone_max_backup_path_multiple`` is required on the same terms and lives in the
    same resource for the same reason: how far a protect path may run against the direct
    distance between its two sites is a statement about the network being bought, not a
    dial on how the search finds it.
    The remaining fields (``compass_sector_count``, ``search_memory_budget``) describe how the
    search scores candidates and how much memory it may consume, which is nobody's
    requirement, so they live in the ``settings`` resource instead and are the only
    fields here that genuinely default.
    """

    compass_sector_count: int = 8  # compass sectors used to score a backbone node's link spread
    # diverse paths each backbone node is asked for (backbone-number-of-diverse-paths)
    backbone_number_of_diverse_paths: int = 3
    # grow backbone until every demand is this near; whole miles, since the great-circle
    # haul it is compared against stands in for an unmeasured last-mile build
    backbone_coverage_target_miles: int = 600
    access_backbone_links: int = 2  # backbone nodes each demand site homes to
    # how many times the direct distance between two backbone nodes a path between them
    # may run; a ratio rather than a mileage, so it means the same thing to a 200-mile link
    # and a 2,000-mile one, and fractional because a ratio has resolution that a target
    # compared against a great-circle haul does not
    backbone_max_backup_path_multiple: float = 3.0
    # how much memory the backbone enumeration may spend
    search_memory_budget: SearchMemoryBudget = field(default_factory=SearchMemoryBudget)

@dataclass(frozen=True)
class NamedLink:
    """A link between two PoPs held by name rather than by id.

    Names are what distinguishes it: ``source`` and ``target`` are PoP display names, as
    the operator wrote them, and the overrides layer resolves them to site ids the way
    it resolves ``forced_backbone_names``. It carries the pruned links as well as the
    forced ones, and says nothing about which tier it acts on -- that comes from which
    list of :class:`OperatorLinks` it was written in, and each list has its own rule.
    """

    source: str
    target: str

@dataclass(frozen=True)
class RoleExclusions:
    """Operator pins that bar a PoP from the backbone, by PoP display name.

    ``prohibited_backbone_names`` bar a PoP from the backbone tier. The overrides
    layer resolves them to site ids. (There is no demand bar: tenant/provider demand is
    inherent to the non-PoP sites, not a tier the synthesizer assigns to a PoP.)
    """

    prohibited_backbone_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class SynthesisParams:
    """Operator choices plus the algorithm :class:`Tuning` for the synthesis.

    ``promote_high_degree_convergences`` toggles the convergence promotion pass: when
    ``True`` a carrier PoP where enough of the synthesis's own lines converge is forced into
    the backbone and the synthesis is redrawn; when ``False`` the pass is skipped and such a
    hub stays a transit node. It is required (no default) at the config layer; the field
    default here is a construction fallback only.

    ``degree_exempt_backbone_names`` are PoPs the diverse path count is not asked of: validation
    neither reports nor refuses their shortfall. It relieves a node of a requirement and
    nothing more -- selection never sees the list, so an exempt node reaches for every
    link its fiber can carry exactly like any other node. Every other node is held to the
    degree as before.

    Where a node's shortfall is the ground's rather than a decision, the list is no longer
    the tool for it: the computed ceiling (see :mod:`synthesizer.ceiling`) lowers such a
    node's target on its own. What is left for the list is the shortfall an operator
    chooses -- cost, a temporary site, traffic they do not want -- which no substrate can
    reveal.
    """

    min_backbone_count: int = 3  # minimum backbone nodes; the search adds more only if needed
    max_backbone_count: int | None = None  # ceiling on backbone nodes; None leaves it uncapped
    forced_backbone_names: tuple[str, ...] = ()  # PoPs pinned as backbone by the operator
    degree_exempt_backbone_names: tuple[str, ...] = ()  # PoPs held to no diverse path count
    exclusions: RoleExclusions = field(default_factory=RoleExclusions)  # role bars
    promote_high_degree_convergences: bool = True  # force high-degree hubs into the backbone
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class OperatorLinks:
    """The links an operator wrote by name, one list per tier they act on.

    ``backbone`` are backbone-backbone pairs pinned into the mesh, ``access`` are demand
    sites pinned onto a named backbone node as one of their homes (the ``forced-homes``
    resource), and ``removed_backbone`` are backbone-backbone pairs pruned from the mesh.
    Which list an entry sits in is what says its tier, so no entry names its own, and the
    three are validated by different rules: a backbone pair looks both names up among the
    carrier PoPs and requires both to be forced backbone nodes, an access link looks its
    source up among everything that is not a carrier PoP, and a pruned pair need only name
    carrier PoPs. :class:`ForcedLinks` is this same information resolved -- names in, ids
    out.
    """

    backbone: tuple[NamedLink, ...] = ()
    access: tuple[NamedLink, ...] = ()
    removed_backbone: tuple[NamedLink, ...] = ()

@dataclass(frozen=True)
class ForcedLinks:
    """Operator-forced links (and backbone pins) resolved to site ids.

    The resolved form of :class:`OperatorLinks`, field for field. ``backbone`` holds each
    backbone-backbone link as an order-independent ``link_key`` pair; ``access`` holds each
    forced home as ``(access_id, backbone_id)``, ordered because the two ends are not
    interchangeable. ``removed_backbone`` holds the pairs the operator pruned from the
    mesh, again as ``link_key`` pairs.
    ``required_backbone`` are the operator-forced backbone ids restricted to the
    eligible set; it is empty until the search plan refines it.
    """

    backbone: frozenset[tuple[str, str]] = frozenset()
    access: frozenset[tuple[str, str]] = frozenset()
    removed_backbone: frozenset[tuple[str, str]] = frozenset()
    required_backbone: frozenset[str] = frozenset()

@dataclass(frozen=True)
class RoleOverrides:
    """Operator role pins resolved from PoP names to concrete site ids.

    ``forced_backbone_ids`` are the ids fixed into the backbone tier;
    ``prohibited_backbone_ids`` are barred from it. ``degree_exempt_backbone_ids`` are
    held to no diverse path count: validation stops reporting their shortfall, while they pick
    peers and are picked as peers like any other node.
    ``forced_links`` carries the operator's pinned links resolved to ids.
    """

    forced_backbone_ids: frozenset[str] = frozenset()
    prohibited_backbone_ids: frozenset[str] = frozenset()
    degree_exempt_backbone_ids: frozenset[str] = frozenset()
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

@dataclass(frozen=True)
class SynthesisInputs:
    """Pre-computed site, link, and shortest-path context shared across backbone sets."""

    access_sites: list[Site]
    carrier_pops: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    eligible_backbone_ids: set[str]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]
    # Each carrier PoP's non-trivial biconnected blocks (a city may sit in several):
    # backbone nodes can be wired into a city-survivable mesh only when they all share
    # one common block. Subsumes the older bridgeless-component oracle (biconnected ⟹ bridgeless).
    carrier_blocks: dict[str, frozenset[int]]

@dataclass(frozen=True)
class MeshRequirements:
    """What each backbone node owes on the mesh: the degree, the exemptions, the ceilings.

    The three always decide one question together -- how many independently failing links
    this particular node is held to -- so they travel as one value rather than as three
    parameters threaded through every check that asks it.

    ``number_of_diverse_paths`` is the operator's configured minimum, asked of every node.
    ``degree_exempt`` are the nodes it is not asked of at all. ``ceilings`` are the computed
    per-node ceilings (see :mod:`synthesizer.ceiling`), which cap the degree where the fiber
    cannot carry it; ``None`` means no substrate was at hand, and every node is then held to
    the flat degree.
    """

    number_of_diverse_paths: int = 3
    degree_exempt: frozenset[str] = frozenset()
    ceilings: Mapping[str, int] | None = None


class ValidationReport(TypedDict):
    """Structured results of validating a synthesis against the hard requirements."""

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
    """All file paths a WAN map's synthesis is computed from.

    ``site_files`` pairs each tenant with its per-tenant sites CSV; the
    tenant is carried here because the CSVs no longer hold a ``tenant`` column.
    ``off_net_path`` is an optional CSV of off-net candidate seats (non-PoP
    locations the operator may force as backbone nodes, reached by local fiber).
    """

    site_files: tuple[tuple[str, Path], ...]
    link_path: Path
    regional_link_paths: tuple[Path, ...] = ()
    off_net_path: Path | None = None

@dataclass(frozen=True)
class SourceFiles:
    """Input file paths recorded in the JSON output for provenance."""

    site_files: tuple[Path, ...]
    link_path: Path

@dataclass(frozen=True)
class SynthesisArtifacts:
    """A completed synthesis bundled with the sites and links it was built from."""

    sites: list[Site]
    fiber_segments: dict[tuple[str, str], FiberSegment]
    synthesis: Synthesis
    validation: ValidationReport

KIND_POP = "PoP"
KIND_ROADM = "ROADM"
# Site kinds that make a site a routable carrier PoP on the backbone graph.
CARRIER_KINDS = frozenset({KIND_POP, KIND_ROADM})

def is_carrier_pop(site: Site) -> bool:
    """Whether a site is a carrier PoP (a routable backbone node)."""
    return site.kind in CARRIER_KINDS
