from __future__ import annotations

import time
from typing import Any

import pytest
import yaml

import seed
from seed import DEFAULT_API, _slug
from test_published_syntheses import published_synthesis, settled

_BUILD_DEADLINE_SECONDS = 900
_BUILD_POLL_SECONDS = 20


def _roster() -> dict[str, dict[str, Any]]:
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(seed.ETC.glob("*.yml"))
    }


def _read_syntheses() -> list[dict[str, Any]]:
    return [
        published_synthesis(DEFAULT_API, tenant, config)
        for tenant, config in _roster().items()
    ]


@pytest.fixture(name="delivered_syntheses")
def delivered_syntheses_fixture() -> list[dict[str, Any]]:
    deadline = time.monotonic() + _BUILD_DEADLINE_SECONDS
    syntheses = _read_syntheses()
    while (not all(settled(synthesis["status"]) for synthesis in syntheses)
            and time.monotonic() < deadline):
        time.sleep(_BUILD_POLL_SECONDS)
        syntheses = _read_syntheses()
    return syntheses
