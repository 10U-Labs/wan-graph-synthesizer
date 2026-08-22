from __future__ import annotations

from collections.abc import Set as AbstractSet

from synthesizer.input_graph import FiberSegment, Site, link_key
from synthesizer.model import (
    SynthesisParams,
    ForcedLinks,
    NamedLink,
    OperatorLinks,
    RoleOverrides,
    is_carrier_pop,
)


def pop_id_by_name(carrier_pops: list[Site]) -> dict[str, str]:
    return {pop.name: pop.id for pop in carrier_pops}

def resolve_pinned_ids(
    names: tuple[str, ...], name_to_id: dict[str, str], label: str
) -> set[str]:
    resolved: set[str] = set()
    for name in names:
        if name not in name_to_id:
            raise ValueError(f"{label} entry not found in the Carrier graph: {name}")
        resolved.add(name_to_id[name])
    return resolved

def reject_override_conflicts(
    forced_backbone: set[str],
    prohibited_backbone: AbstractSet[str] = frozenset(),
) -> None:
    clash = forced_backbone & prohibited_backbone
    if clash:
        raise ValueError(
            "PoPs cannot be both forced onto and prohibited from the backbone tier: "
            f"{sorted(clash)}"
        )


def _resolve_operator_pins(
    sites: list[Site],
    params: SynthesisParams,
) -> tuple[set[str], set[str], set[str]]:
    carrier_pops = [site for site in sites if is_carrier_pop(site)]
    name_to_id = pop_id_by_name(carrier_pops)
    forced_backbone = resolve_pinned_ids(
        params.forced_backbone_names, name_to_id, "forced_backbone"
    )
    prohibited_backbone = resolve_pinned_ids(
        params.exclusions.prohibited_backbone_names, name_to_id, "prohibited_backbone"
    )
    degree_exempt = resolve_pinned_ids(
        params.degree_exempt_backbone_names, name_to_id, "degree_exempt_backbone"
    )
    reject_override_conflicts(forced_backbone, prohibited_backbone)
    return forced_backbone, prohibited_backbone, degree_exempt


def _forced_backbone_endpoint(
    name: str, name_to_id: dict[str, str], forced_backbone: set[str], label: str
) -> str:
    if name not in name_to_id:
        raise ValueError(f"{label} backbone not found in the Carrier graph: {name}")
    backbone_id = name_to_id[name]
    if backbone_id not in forced_backbone:
        raise ValueError(f"{label} endpoint must be a forced backbone node: {name}")
    return backbone_id


def _backbone_backbone_pair(
    path: NamedLink, name_to_id: dict[str, str], forced_backbone: set[str]
) -> tuple[str, str]:
    left = _forced_backbone_endpoint(path.source, name_to_id, forced_backbone, "forced-path")
    right = _forced_backbone_endpoint(path.target, name_to_id, forced_backbone, "forced-path")
    return link_key(left, right)


def _forced_home_pair(
    home: NamedLink,
    access_name_to_id: dict[str, str],
    name_to_id: dict[str, str],
    forced_backbone: set[str],
) -> tuple[str, str]:
    if home.source not in access_name_to_id:
        raise ValueError(f"forced-home access node not found: {home.source}")
    backbone = _forced_backbone_endpoint(home.target, name_to_id, forced_backbone, "forced-home")
    return access_name_to_id[home.source], backbone


def _excluded_backbone_endpoint(name: str, name_to_id: dict[str, str]) -> str:
    if name not in name_to_id:
        raise ValueError(f"prohibited-path backbone not found in the Carrier graph: {name}")
    return name_to_id[name]


def _removed_backbone_pair(path: NamedLink, name_to_id: dict[str, str]) -> tuple[str, str]:
    left = _excluded_backbone_endpoint(path.source, name_to_id)
    right = _excluded_backbone_endpoint(path.target, name_to_id)
    return link_key(left, right)


def _removed_backbone_links(
    paths: tuple[NamedLink, ...],
    name_to_id: dict[str, str],
) -> frozenset[tuple[str, str]]:
    return frozenset(_removed_backbone_pair(path, name_to_id) for path in paths)


def resolve_forced_links(
    links: OperatorLinks,
    sites: list[Site],
    forced_backbone: set[str],
) -> ForcedLinks:
    name_to_id = pop_id_by_name([site for site in sites if is_carrier_pop(site)])
    access_name_to_id = {
        site.name: site.id for site in sites if not is_carrier_pop(site)
    }
    return ForcedLinks(
        backbone=frozenset(
            _backbone_backbone_pair(path, name_to_id, forced_backbone)
            for path in links.backbone
        ),
        access=frozenset(
            _forced_home_pair(home, access_name_to_id, name_to_id, forced_backbone)
            for home in links.access
        ),
        removed_backbone=_removed_backbone_links(links.removed_backbone, name_to_id),
    )


def apply_role_overrides(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    params: SynthesisParams,
    links: OperatorLinks = OperatorLinks(),
) -> tuple[list[Site], dict[tuple[str, str], FiberSegment], RoleOverrides]:
    forced_backbone, prohibited_backbone, degree_exempt = _resolve_operator_pins(
        sites, params
    )
    overrides = RoleOverrides(
        forced_backbone_ids=frozenset(forced_backbone),
        prohibited_backbone_ids=frozenset(prohibited_backbone),
        degree_exempt_backbone_ids=frozenset(degree_exempt),
        forced_links=resolve_forced_links(links, sites, forced_backbone),
    )
    return sites, fiber_segments, overrides
