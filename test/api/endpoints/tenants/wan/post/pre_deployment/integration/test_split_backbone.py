"""Integration test: a synthesis that falls into two groups is refused, not published.

A published WAN is what an operator builds from, so one whose sites cannot all reach each
other is worse than no WAN at all: it reads as a finished national network and carries no
traffic between its halves. Nothing outside the build would say so -- the status reads
``success``, every site holds the links it was asked for, and the split shows up only in a
finding nothing used to read (GitHub issue #68).

The gate is in ``synthesizer.stages.finalize``, and a unit test can show it fires. What only
this tier can show is that firing it stops the publication: the whole of
``synthesizer.handler._build_wan`` runs here over a fake store, with the real loaders, the
real config assembly and the real ``finalize``, and what is asserted is what the store holds
afterwards.

The carrier map is two triangles no fiber joins -- three cities in Virginia and three in
Utah -- and the synthesis bought every segment of it. Each site therefore holds the two
independently failing links its tenant asks for, inside its own triangle, which is what
makes the case worth driving: every other finding in the report passes and the synthesis is
still two networks.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import load_module_from_path
from test_s3_store_mock import fake_s3
from synthesizer.input_graph import FiberSegment, Site
from synthesizer.model import Synthesis, SynthesisMetrics, is_carrier_pop

_PATH = REPO_ROOT / "src/api/endpoints/tenants/wan/post/lambdas/synthesizer/handler.py"
_TENANT = "split"

# Three cities in Virginia and three in Utah, each triangle wired to itself and to nothing
# else, so no synthesis over this map can be one network.
_CITIES = {
    "Ashburn": ("VA", 39.0438, -77.4874),
    "Sterling": ("VA", 39.0062, -77.4286),
    "Reston": ("VA", 38.9586, -77.3570),
    "Salt Lake City": ("UT", 40.7608, -111.8910),
    "Ogden": ("UT", 41.2230, -111.9738),
    "Provo": ("UT", 40.2338, -111.6585),
}
_TRIANGLES = (("Ashburn", "Sterling", "Reston"), ("Salt Lake City", "Ogden", "Provo"))


def _city_row(municipality: str) -> dict[str, Any]:
    """One carrier point, as the merged carriers serve it."""
    state, latitude, longitude = _CITIES[municipality]
    return {
        "municipality": municipality,
        "state": state,
        "country": "United States",
        "latitude": latitude,
        "longitude": longitude,
    }


def _fiber_rows() -> list[dict[str, Any]]:
    """The fiber of both triangles, each segment named by its two endpoints' cities."""
    return [
        {
            "a_municipality": near,
            "a_state": _CITIES[near][0],
            "z_municipality": far,
            "z_state": _CITIES[far][0],
        }
        for triangle in _TRIANGLES
        for near, far in zip(triangle, (*triangle[1:], triangle[0]))
    ]


# The six resources naming sites and links the operator has pinned, prohibited or excused.
# This tenant pins nothing, so each is delivered as the empty document seed writes for a
# config that names nobody, and the synthesis is left to the map.
_NAMES_NOBODY = (
    "forced-backbone-nodes",
    "forced-paths",
    "forced-homes",
    "prohibited-backbone-nodes",
    "prohibited-paths",
    "degree-exempt-backbone-nodes",
)


def _config_documents() -> dict[str, Any]:
    """The tenant's config, one document per resource, as ``scripts/seed.py`` PUTs them."""
    return {
        **{resource: [] for resource in _NAMES_NOBODY},
        "backbone-node-count": {"min": 2, "max": 6},
        "backbone-number-of-diverse-paths": {"degree": 2},
        "access-homing-degree": {"degree": 2},
        "convergence-promotion": {"promote": False},
        "knobs": {
            "backbone_coverage_target_miles": 500,
            "backbone_max_backup_path_multiple": 3,
        },
        "settings": {},
        "label": {"label": "Split"},
    }


def _store() -> dict[str, bytes]:
    """Every object the build reads, holding the two-triangle map and the tenant's config."""
    objects: dict[str, Any] = {
        "carriers/merge/pops.json": [_city_row(city) for city in _CITIES],
        "carriers/merge/fiber-segments.json": _fiber_rows(),
        f"tenants/{_TENANT}/locations.json": [
            {"name": "Dulles Site", **_city_row("Ashburn")}
        ],
        f"tenants/{_TENANT}/provider-regions.json": [],
        f"tenants/{_TENANT}/off-net.json": [],
    }
    objects |= {
        f"tenants/{_TENANT}/{resource}.json": document
        for resource, document in _config_documents().items()
    }
    return {key: json.dumps(value).encode("utf-8") for key, value in objects.items()}


def _synthesis_over_every_segment(
    sites: list[Site], fiber_segments: dict[tuple[str, str], FiberSegment], *_rest: Any
) -> Synthesis:
    """A synthesis seating every carrier point and buying every segment of fiber on offer.

    This stands in for the fiber choice, which is the step a split comes out of: the map
    holds no fiber between the two triangles, so the segments bought leave the six sites in
    two groups however many of them are taken.
    """
    return Synthesis(
        backbone_ids=tuple(
            sorted(site.id for site in sites if is_carrier_pop(site))
        ),
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys=set(fiber_segments),
        path_uses=[],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


@pytest.fixture(name="store")
def store_fixture(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Run the whole build over the two-triangle map and return the store it left behind."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module = load_module_from_path("split_backbone_handler", _PATH)
    monkeypatch.setattr(module, "synthesize_two_tier", _synthesis_over_every_segment)
    objects = _store()
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler({"tenant": _TENANT}, None)
    return objects


def test_a_synthesis_in_two_groups_publishes_no_wan(store: dict[str, bytes]) -> None:
    """The build writes no WAN, so no operator is ever handed the two-piece network."""
    assert f"tenants/{_TENANT}/wan.json" not in store


def test_the_recorded_reason_names_the_groups_the_synthesis_fell_into(
    store: dict[str, bytes]
) -> None:
    """The ``fail`` status says the synthesis fell into two groups, not merely that it failed.

    Without this the test above would pass just as well on a build that died loading its
    own inputs, and the gate would be unproven.
    """
    status = json.loads(store[f"tenants/{_TENANT}/wan-status.json"])
    assert "falls into 2 groups" in status["reason"]
