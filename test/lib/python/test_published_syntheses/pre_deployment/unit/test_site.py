"""Unit tests for rebuilding a published node as the site the distance helper takes."""

from __future__ import annotations

from typing import Any

from synthesizer.input_graph import Site
from test_published_syntheses import site


def test_a_published_node_is_rebuilt_as_the_site_it_describes() -> None:
    """Every attribute the rebuilt site is measured by comes off the published node.

    The coordinates arrive as the two-element list a JSON document holds rather than as a
    tuple, which is the form the store hands back and so the form the rebuild has to take.
    """
    published: dict[str, Any] = {
        "id": "pdx", "name": "Portland", "kind": "PoP", "coords": [45.5, -122.7],
    }
    assert site(published) == Site("pdx", "Portland", "PoP", (45.5, -122.7))
