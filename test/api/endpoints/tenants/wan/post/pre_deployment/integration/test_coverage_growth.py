from __future__ import annotations

import fixtures
from synthesizer.coverage import coverage_report
from synthesizer.model import SynthesisParams, Tuning, is_carrier_pop

_SITES = [
    fixtures.carrier_pop("hub_a", 0.0, 0.0),
    fixtures.carrier_pop("hub_b", 0.05, 0.0),
    fixtures.carrier_pop("cape", 0.0, 7.4),
    fixtures.carrier_pop("plains", 0.0, -7.39),
    fixtures.access_site("east_site", 0.0, 7.5),
    fixtures.access_site("west_site", 0.0, -7.49),
]
_LINKS = fixtures.fiber_segments_from({
    ("hub_a", "hub_b"): 1.0,
    ("cape", "hub_a"): 1.0, ("cape", "hub_b"): 1.0,
    ("plains", "hub_a"): 1.0, ("plains", "hub_b"): 1.0,
})
_TARGET_MILES = 100
_PARAMS = SynthesisParams(
    min_backbone_count=2,
    forced_backbone_names=("hub_a", "hub_b"),
    promote_high_degree_convergences=False,
    tuning=Tuning(
        backbone_number_of_diverse_paths=2,
        backbone_coverage_target_miles=_TARGET_MILES,
    ),
)
ARTIFACTS = fixtures.run_synthesis(_SITES, _LINKS, _PARAMS)


def test_the_synthesis_seats_a_hub_for_each_of_the_two_far_sites() -> None:
    assert sorted(ARTIFACTS.synthesis.backbone_ids) == ["cape", "hub_a", "hub_b", "plains"]


def test_the_delivered_synthesis_reports_its_coverage_target_met() -> None:
    delivered = coverage_report(
        ARTIFACTS.synthesis.backbone_ids,
        [site for site in ARTIFACTS.sites if not is_carrier_pop(site)],
        {site.id: site for site in ARTIFACTS.sites},
        _TARGET_MILES,
    )
    assert delivered["met"] is True
