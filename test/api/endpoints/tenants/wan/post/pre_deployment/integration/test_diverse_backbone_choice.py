from __future__ import annotations

import fixtures
from synthesizer.model import RoleExclusions, SynthesisParams, Tuning

_TWO_SEATS = SynthesisParams(
    min_backbone_count=2,
    max_backbone_count=2,
    exclusions=RoleExclusions(prohibited_backbone_names=fixtures.funnel_transit_names()),
    promote_high_degree_convergences=False,
    tuning=Tuning(backbone_number_of_diverse_paths=2),
)
ARTIFACTS = fixtures.run_synthesis(
    fixtures.funnel_sites(), fixtures.FUNNEL_LINKS, _TWO_SEATS
)


def test_the_synthesis_seats_two_backbone_sites() -> None:
    assert len(ARTIFACTS.synthesis.backbone_ids) == 2


def test_the_backbone_holds_the_site_whose_fiber_carries_the_most_paths() -> None:
    assert "spread" in ARTIFACTS.synthesis.backbone_ids


def test_the_backbone_leaves_one_of_the_funnelled_sites_out() -> None:
    seated = set(ARTIFACTS.synthesis.backbone_ids)
    assert not {"funnel", "second_funnel"} <= seated
