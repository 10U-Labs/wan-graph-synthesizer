"""Integration test: a whole synthesis stays in one piece when any one city goes dark.

A tenant that buys two ways out of every backbone node is buying a backbone that carries
traffic through the loss of a city, and that is a property of the whole network rather than
of any one site in it. A site can hold both of its own ways out and still end up cut off
from most of its peers, because the cities its peers depend on are the ones that failed.
Three of the five live tenants published a network in exactly that state: the loss of
Atlanta, GA left Ashburn, VA and New York, NY with no way to DAF's other nine backbone
nodes, and eight more cities each split it somewhere (GitHub issue #112).

The graph here is the smallest thing that can go wrong that way. Two triangles of fiber share
the city ``mid``, and a thirty-mile way from ``b`` to ``c`` goes round it. Each of the four
seats holds its two ways out inside its own triangle, so every path read off the fiber
crosses ``mid``, while the fiber those paths were chosen out of goes round it perfectly well.

No fixture in this directory could produce that before. ``fixtures.ring_artifacts`` and the
graphs beside it give each site two fiber directions and no more, so a site's two ways out
are the two ways round the ring and their union is the ring itself -- a network no one city's
loss splits, whatever the code under test does. That is why
``test_synthesize_two_tier.test_backbone_survives_any_single_city`` passed throughout.
"""

from __future__ import annotations

import fixtures

_SITES = ("a", "b", "c", "d")
_ASKED_FOR = 2
# Two triangles sharing ``mid``, and the one length of fiber that goes past it. The way round
# runs forty miles against the twenty-four ``a`` and ``c`` are apart, well inside the default
# backup path multiple of three, so nothing but the network's own shape decides this.
_SEGMENTS = {
    ("a", "b"): 10.0, ("a", "mid"): 11.0, ("b", "mid"): 12.0,
    ("c", "d"): 10.0, ("c", "mid"): 13.0, ("d", "mid"): 14.0,
    ("b", "c"): 30.0,
}
_TRANSIT = ("mid",)
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR, _TRANSIT)


def test_the_published_backbone_survives_the_loss_of_any_one_city() -> None:
    """No one city's loss leaves the four seats in two groups that cannot reach each other.

    What the tenant is paying for, asserted against a network the whole pipeline built. Each
    seat holds its two ways out either way; what this asks is the separate question of
    whether the paths those ways out add up to still join everybody once ``mid`` is gone.
    """
    assert ARTIFACTS.validation["backbone_mesh_survives_any_one_site_loss"] is True
