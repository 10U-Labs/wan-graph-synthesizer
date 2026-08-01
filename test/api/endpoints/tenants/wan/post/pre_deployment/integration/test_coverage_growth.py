"""Integration test: a whole design honours its coverage target when two sites deadlock it.

The unit tier can show the growth loop seating a second hub after the first. It cannot show
that a design comes out of the pipeline covered, because the base search, the city-survival
gate, the mesh selection and validation all sit between a round of growth and a published
backbone, and any of them could give the seat back. So the geometry is run through the whole
design here and the delivered network is measured against the target rather than the loop
watched.

The graph is the shape DAF stopped short on (GitHub issue #41). Two sites sit some five
hundred miles off the base pair, seven and a half degrees to either side, and two thirds of
a mile apart in haul. One hub reaches each, and neither can reach both. Seating either one
rescues its site and hands the top of the worst-haul list to the other, so a design judged
by that one number sees a five-hundred-mile rescue as two thirds of a mile of progress and
declines to spend a seat on it. This file's own sibling, ``test_diverse_backbone_choice``,
carries no demand at all and so cannot ask the question; the fixture here exists to put
sites on the map and let coverage growth run inside a real design.
"""

from __future__ import annotations

import fixtures
from synthesizer.coverage import coverage_report
from synthesizer.model import DesignParams, Tuning, is_carrier_pop

# The base pair sits at the origin; "cape" is a tenth of a degree short of the eastern site
# and "plains" a tenth short of the western one. The sites are fifteen degrees apart, so no
# single hub can serve both, and the western one is set a hundredth of a degree nearer than
# the eastern so the two hauls differ by less than a mile rather than tying exactly.
_VERTICES = [
    fixtures.carrier_pop("hub_a", 0.0, 0.0),
    fixtures.carrier_pop("hub_b", 0.05, 0.0),
    fixtures.carrier_pop("cape", 0.0, 7.4),
    fixtures.carrier_pop("plains", 0.0, -7.39),
    fixtures.access_vertex("east_site", 0.0, 7.5),
    fixtures.access_vertex("west_site", 0.0, -7.49),
]
# Every hub and every site hangs off both base nodes, so each grown backbone is buildable
# and every site homes: what the design settles on is decided by geography alone.
_EDGES = fixtures.physical_edges_from({
    ("hub_a", "hub_b"): 1.0,
    ("cape", "hub_a"): 1.0, ("cape", "hub_b"): 1.0,
    ("plains", "hub_a"): 1.0, ("plains", "hub_b"): 1.0,
    ("east_site", "hub_a"): 1.0, ("east_site", "hub_b"): 1.0,
    ("west_site", "hub_a"): 1.0, ("west_site", "hub_b"): 1.0,
})
# The base pair is pinned so the strength search cannot settle anywhere else, leaving the
# coverage pass as the only thing that can seat the other two. The convergence promotion is
# off, since a hub forced in afterwards would answer a different question than this one.
_TARGET_MILES = 100
_PARAMS = DesignParams(
    min_backbone_count=2,
    forced_backbone_names=("hub_a", "hub_b"),
    datacenter_cities=None,
    promote_high_degree_convergences=False,
    tuning=Tuning(
        backbone_number_of_diverse_paths=2,
        backbone_coverage_target_miles=_TARGET_MILES,
    ),
)
ARTIFACTS = fixtures.run_design(_VERTICES, _EDGES, _PARAMS)


def test_the_design_seats_a_hub_for_each_of_the_two_far_sites() -> None:
    """Both far hubs are seated, though neither one alone moves the worst haul by a mile."""
    assert sorted(ARTIFACTS.design.backbone_ids) == ["cape", "hub_a", "hub_b", "plains"]


def test_the_delivered_design_reports_its_coverage_target_met() -> None:
    """The network that comes out leaves every site inside the target it was built to.

    Which is the claim the seats above are only evidence for: an operator reads the
    coverage the design delivered, not the rounds the search took to get there.
    """
    delivered = coverage_report(
        ARTIFACTS.design.backbone_ids,
        [vertex for vertex in ARTIFACTS.vertices if not is_carrier_pop(vertex)],
        {vertex.id: vertex for vertex in ARTIFACTS.vertices},
        _TARGET_MILES,
    )
    assert delivered["met"] is True
