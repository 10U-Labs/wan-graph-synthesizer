"""Integration test: a whole synthesis stays in one piece when any one city goes dark.

A tenant that asks for two ways out of every backbone node is asking for a backbone that carries
traffic through the loss of a city, and that is a property of the whole network rather than
of any one site in it. A site can hold both of its own ways out and still end up cut off
from most of its peers, because the cities its peers depend on are the ones that failed.
Three of the five live tenants published a network in exactly that state: the loss of
Atlanta, GA left Ashburn, VA and New York, NY with no way to DAF's other nine backbone
nodes, and eight more cities each split it somewhere (GitHub issue #112).

The graph here is the smallest thing that can go wrong that way. Two lobes of fiber are
joined over a short way through the city ``mid`` and a long way round through ``w``: ``a``
and ``b`` sit on one side, ``c`` and ``d`` on the other, and the way through ``w`` runs
forty miles where ``b`` and ``c`` are ten apart, which is past what the tenant's backup path
multiple of three allows for that pair. So no site reaches for it, every path read off the
fiber crosses ``mid``, and the fiber those paths were chosen out of goes round ``mid``
perfectly well.

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
# The two lobes, and the fiber through ``w`` that goes past ``mid``. The way round taken is
# the fifty miles from ``a`` to ``c`` through ``w``, against the twenty those two are apart,
# which is inside the default backup path multiple of three -- while the forty miles from
# ``b`` to ``c`` the same fiber offers is not, against the ten they are apart, which is why
# the reading leaves that fiber undrawn in the first place.
_SEGMENTS = {
    ("a", "b"): 10.0, ("a", "mid"): 15.0, ("b", "mid"): 5.0,
    ("c", "d"): 10.0, ("c", "mid"): 5.0, ("d", "mid"): 15.0,
    ("b", "w"): 20.0, ("w", "c"): 20.0,
}
_TRANSIT = ("mid", "w")
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR, _TRANSIT)


def test_the_published_backbone_survives_the_loss_of_any_one_city() -> None:
    """No one city's loss leaves the four seats in two groups that cannot reach each other.

    What the tenant is paying for, asserted against a network the whole pipeline built. Each
    seat holds its two ways out either way; what this asks is the separate question of
    whether the paths those ways out add up to still join everybody once ``mid`` is gone.
    """
    assert ARTIFACTS.validation["backbone_mesh_survives_any_one_site_loss"] is True
