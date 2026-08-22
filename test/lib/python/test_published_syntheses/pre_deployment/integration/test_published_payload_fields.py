from __future__ import annotations

from dataclasses import replace
from typing import Any

import fixtures
from synthesizer import collections as published
from synthesizer.model import OperatorLinks, Tuning
from synthesizer.output import synthesis_payload

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

_NODE_FIELDS = ("id", "name", "kind", "coords")
_SITE_FIELDS = (*_NODE_FIELDS, "exempt_from_distance_constraint")
_LINK_FIELDS = ("source_id", "target_id", "distance_miles", "path")
_PATH_FIELDS = ("source_id", "target_id", "distance_miles", "link_kind")


def _subjects() -> list[tuple[str, list[dict[str, Any]], tuple[str, ...]]]:
    return [
        ("backbone-nodes", published.backbone_nodes(_PAYLOAD), _NODE_FIELDS),
        ("tenant-nodes", published.tenant_nodes(_PAYLOAD), _SITE_FIELDS),
        ("backbone-links", published.backbone_links(_PAYLOAD), _LINK_FIELDS),
        ("paths", published.paths(_PAYLOAD), _PATH_FIELDS),
    ]


def test_every_collection_the_helpers_read_has_a_record_in_it() -> None:
    assert [name for name, records, _ in _subjects() if not records] == []


def test_every_field_the_helpers_read_is_one_the_collections_publish() -> None:
    absent = [
        (name, field)
        for name, records, fields in _subjects()
        for field in fields
        for record in records
        if field not in record
    ]
    assert absent == []
