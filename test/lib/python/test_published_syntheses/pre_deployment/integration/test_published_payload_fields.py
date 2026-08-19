"""Contract: the helpers read a published network by names the synthesizer actually emits.

The measuring helpers reach into a published document by name -- a node's id, name, kind
and coordinates, a demand site's exemption flag, a link's two endpoints, distance and
path, and a fiber segment's two ends, length and whether it is carrier fiber or an access
homing. Those names are a contract with ``synthesizer.collections``, which
slices the synthesis payload into the collections the store holds, and nothing holds the two
sides against each other. A field renamed on the producing side surfaces today as a
``KeyError`` in the middle of a live post-deployment run, an hour and a deployment after
the push that caused it; a field that became optional surfaces as nothing at all, because
the link carrying it is discarded and a network with every link discarded reads exactly
like a network with no over-long paths.

The payload is built in process from the suite's ring fixtures, so what is held to account
here is what the synthesizer emits rather than what some deployment happens to hold.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import fixtures
from synthesizer import collections as published
from synthesizer.model import OperatorLinks, Tuning
from synthesizer.output import synthesis_payload

# The suite's ring parameters with every one of its PoPs seated, so the payload carries a
# record of each kind the helpers read: a backbone node, a demand site homed onto it, and
# a backbone-to-backbone link. Two diverse paths is what a ring's fiber can hold, each of
# its PoPs having two fiber directions.
_SEATED_RING = replace(
    fixtures.ring_params(),
    forced_backbone_names=("P0", "P1", "P2", "P3", "P4", "P5"),
    tuning=Tuning(backbone_number_of_diverse_paths=2),
)
_PAYLOAD = synthesis_payload(
    fixtures.sample_sources(),
    fixtures.forced_link_artifacts(
        _SEATED_RING, OperatorLinks(), fixtures.ring_inputs_with_demand("S1", "P0")
    ),
)

# What the helpers read off each kind of record, under the name they read it by.
_NODE_FIELDS = ("id", "name", "kind", "coords")
_SITE_FIELDS = (*_NODE_FIELDS, "exempt_from_distance_constraint")
_LINK_FIELDS = ("source_id", "target_id", "distance_miles", "path")
# ``edge_kind`` is what separates a segment of carrier fiber from an access homing, and the
# two are served in one collection. A reader that could not tell them apart would measure
# a link against a path through a demand site's homing, which is not fiber.
_EDGE_FIELDS = ("source_id", "target_id", "distance_miles", "edge_kind")


def _subjects() -> list[tuple[str, list[dict[str, Any]], tuple[str, ...]]]:
    """Each published collection the helpers read, beside the fields they read off it."""
    return [
        ("backbone-nodes", published.backbone_nodes(_PAYLOAD), _NODE_FIELDS),
        ("tenant-nodes", published.tenant_nodes(_PAYLOAD), _SITE_FIELDS),
        ("backbone-links", published.backbone_links(_PAYLOAD), _LINK_FIELDS),
        ("edges", published.edges(_PAYLOAD), _EDGE_FIELDS),
    ]


def test_every_collection_the_helpers_read_has_a_record_in_it() -> None:
    """The synthesis under test publishes all four collections, so the contract below binds.

    Without this the field check passes on a payload carrying no links at all, which is
    the same shape of vacuous pass the helpers themselves can produce.
    """
    assert [name for name, records, _ in _subjects() if not records] == []


def test_every_field_the_helpers_read_is_one_the_collections_publish() -> None:
    """No record the synthesizer emits is missing a name the helpers reach for."""
    absent = [
        (name, field)
        for name, records, fields in _subjects()
        for field in fields
        for record in records
        if field not in record
    ]
    assert absent == []
