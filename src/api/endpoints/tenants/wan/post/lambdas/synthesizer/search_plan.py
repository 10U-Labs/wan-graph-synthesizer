from __future__ import annotations

from dataclasses import dataclass, field

from synthesizer.model import ForcedLinks, Tuning


@dataclass(frozen=True)
class _SearchPlan:
    backbone_candidates: list[str]
    strength_by_id: dict[str, float]
    tuning: Tuning = field(default_factory=Tuning)
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)
    seat_cap: int | None = None

    @property
    def required_backbone(self) -> frozenset[str]:
        return self.forced_links.required_backbone
