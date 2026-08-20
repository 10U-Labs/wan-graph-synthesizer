"""Unit tests for the published links drawn further than their own fiber made necessary.

The helper reads the fiber a published network carries and asks, of each backbone link,
whether it took the shortest way over that fiber between the two sites it joins. Nothing
outside the build could ask this before, and the reason to ask it is that the proof behind
the mesh once read no distance at all: it counted paths that share no city, so a link
between two sites a few hundred miles apart could be drawn across an ocean and every
published number about it would look well formed (GitHub issues #44 and #57).

The fiber below is two ten-mile segments through ``hub`` and one hundred-mile segment straight
across, so the shortest way from ``west`` to ``east`` is twenty miles and a tenant allowing
three times the direct distance allows sixty. The two access homings are there because the
published links collection carries them beside the fiber: counted as segments they would make
``west`` two miles from ``east`` through a demand site, which is not fiber any link can be
laid along.

Two of the four cases are links the helper discards without recording that it did, and no
published network will ever hold one: a real synthesis joins no node to itself and names no
site its own fiber does not reach. They are tested because a helper that discarded every
link would return the empty list a sound network returns, and the assertion standing on it
could not tell the two apart.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import detoured_links

_LINKS: list[dict[str, Any]] = [
    {"source_id": "west", "target_id": "hub", "distance_miles": 10.0,
     "link_kind": "carrier_physical"},
    {"source_id": "hub", "target_id": "east", "distance_miles": 10.0,
     "link_kind": "carrier_physical"},
    {"source_id": "west", "target_id": "east", "distance_miles": 100.0,
     "link_kind": "carrier_physical"},
    {"source_id": "site", "target_id": "west", "distance_miles": 1.0,
     "link_kind": "tenant_to_backbone"},
    {"source_id": "site", "target_id": "east", "distance_miles": 1.0,
     "link_kind": "tenant_to_backbone"},
]


def _synthesis(source: str, target: str, distance: float) -> dict[str, Any]:
    """A published network of that fiber carrying one drawn link between two ids."""
    return {
        "links": _LINKS,
        "max_backup_path_multiple": 3.0,
        "links": [
            {
                "source_id": source,
                "target_id": target,
                "distance_miles": distance,
                "path": [source, target],
            }
        ],
    }


def test_a_link_drawn_past_the_bound_is_reported_by_the_path_it_takes() -> None:
    """A thousand miles of path between two sites twenty miles of fiber apart is fifty times out.

    Reported by its path, which is what names the detour to whoever reads the failure: the
    paths GitHub issue #44 produced ran through Paris and through Tokyo.
    """
    assert [path for path, _ in detoured_links(_synthesis("west", "east", 1000.0))] == [
        "west -> east"
    ]


def test_a_link_is_not_measured_against_a_path_through_an_access_homing() -> None:
    """Forty miles is twice the fiber and inside the bound, though it is twenty times a homing.

    ``site`` homes to both backbone nodes at a mile each, so a reader counting the homings
    as fiber would put ``west`` two miles from ``east`` and condemn this link. No link can be
    laid over a demand site's homing, so the shortest path it is held to is the twenty
    miles of carrier fiber through ``hub``.
    """
    assert not detoured_links(_synthesis("west", "east", 40.0))


def test_a_link_whose_two_ends_are_the_same_site_is_discarded() -> None:
    """A site joined to itself has no path over the fiber to be measured against."""
    assert not detoured_links(_synthesis("west", "west", 1000.0))


def test_a_link_naming_a_site_the_published_fiber_does_not_reach_is_discarded() -> None:
    """An endpoint no fiber segment leads to has no shortest path, so the bound says nothing."""
    assert not detoured_links(_synthesis("west", "ghost", 1000.0))
