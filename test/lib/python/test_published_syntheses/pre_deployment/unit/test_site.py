from __future__ import annotations

from typing import Any

from synthesizer.input_graph import Site
from test_published_syntheses import site_from_node


def test_a_published_node_is_rebuilt_as_the_site_it_describes() -> None:
    published: dict[str, Any] = {
        "id": "pdx", "name": "Portland", "kind": "PoP", "coords": [45.5, -122.7],
    }
    assert site_from_node(published) == Site("pdx", "Portland", "PoP", (45.5, -122.7))
