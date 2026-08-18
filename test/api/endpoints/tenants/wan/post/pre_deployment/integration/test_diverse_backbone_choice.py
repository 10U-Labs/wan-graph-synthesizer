"""Integration test: which sites a whole synthesis settles on when the measures disagree.

The unit tier can show that the score ranks a well-connected site above one with more fiber.
It cannot show that the ranking survives the pipeline -- feasibility, the city-survival
gate, the last-mile tie-break and the coverage growth all sit between a score and a
backbone, and any of them could put the site back. So the same graph is run through the
whole design here and the backbone is asserted rather than the score.

The graph is the one fixture where fiber segment count and path diversity rank sites
differently (see ``fixtures.FUNNEL_EDGES``). Two sites have five segments each that converge
on the same two upstream cities, so each carries two paths that fail independently; one
site has three segments leaving to three separate cities and carries three. Ranked by segments
the two funnels are the strongest pair and the spread site is left out; ranked by
diversity the spread site is seated. Two seats are all the design gets, so the two
rankings cannot both be satisfied and the backbone says which one ran.
"""

from __future__ import annotations

import fixtures
from synthesizer.model import DesignParams, Tuning

# Two seats exactly: the floor is what the search settles at once a feasible set exists,
# and with no demand vertices on the graph the coverage pass never grows past it. The
# convergence promotion is off for the same reason -- a hub forced in afterwards would
# answer a different question than the one this file asks.
_TWO_SEATS = DesignParams(
    min_backbone_count=2,
    max_backbone_count=2,
    datacenter_cities=fixtures.funnel_datacenter_cities(),
    promote_high_degree_convergences=False,
    tuning=Tuning(backbone_number_of_diverse_paths=2),
)
ARTIFACTS = fixtures.run_design(
    fixtures.funnel_vertices(), fixtures.FUNNEL_EDGES, _TWO_SEATS
)


def test_the_design_seats_two_backbone_sites() -> None:
    """The search stops at the floor, so the backbone is the two seats being contested."""
    assert len(ARTIFACTS.design.backbone_ids) == 2


def test_the_backbone_holds_the_site_whose_fiber_carries_the_most_paths() -> None:
    """The spread site is seated, though two other candidates have more fiber segments.

    Under the segment-count term the two funnels were the strongest pair and this site placed
    third, so a design ranking sites by how much fiber touches them leaves it out.
    """
    assert "spread" in ARTIFACTS.design.backbone_ids


def test_the_backbone_leaves_one_of_the_funnelled_sites_out() -> None:
    """Only one funnel is seated, since the second seat went to the diverse site."""
    seated = set(ARTIFACTS.design.backbone_ids)
    assert not {"funnel", "second_funnel"} <= seated
