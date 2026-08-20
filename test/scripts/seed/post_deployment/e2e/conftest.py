"""The published networks seed asked for, paired with what each tenant's config demands.

``delivered_syntheses`` reads what the synthesizer published for every tenant the roster in
``etc/`` declares. The roster is the list of tenants and ``seed`` supplies the
file-stem-to-tenant-id rule, so a tenant added to git is one this tier starts asking about
with no edit here. The reading itself is ``test_published_syntheses.published_synthesis``, which
asks the API for each tenant's build state and its five published collections; nothing here
opens the store the synthesizer writes to. Each entry is a plain mapping of thirteen keys:
``tenant``; the ``target_miles``, ``max_backup_path_multiple``, ``number_of_diverse_paths``,
``seat_cap``, pinned ``forced`` cities and pinned ``forced_paths`` the config sets; the
``status`` document the GET passes through and the ``lower_bound_miles`` it reports; and the
published ``backbone``, ``demand``, ``links`` and ``links`` collections that status can be
measured against. A tenant whose build is not ``success`` has no network to read and carries
all four empty.
"""
from __future__ import annotations

import time
from typing import Any

import pytest
import yaml

import seed
from seed import DEFAULT_API, _slug
from test_published_syntheses import published_synthesis, settled

# How long the tenants are given to finish building, and how often they are asked. The
# builds are started by the ``seeding`` job in .github/workflows/seed.yml, which the one
# test file that uses this fixture runs after: the POST that starts a build records
# ``creating`` before it answers, so by the time seeding returns every tenant is at
# ``creating`` or later and there is no earlier build left to mistake for the current one.
# Waiting for the state to leave ``creating`` and ``synthesizing`` is then the whole of
# the question (GitHub issue #47).
_BUILD_DEADLINE_SECONDS = 900
_BUILD_POLL_SECONDS = 20


def _roster() -> dict[str, dict[str, Any]]:
    """Each tenant id the roster declares, with the whole config git holds for it."""
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(seed.ETC.glob("*.yml"))
    }


def _read_syntheses() -> list[dict[str, Any]]:
    """Every declared tenant's published network beside the demands its config makes of it."""
    return [
        published_synthesis(DEFAULT_API, tenant, config)
        for tenant, config in _roster().items()
    ]


@pytest.fixture(name="delivered_syntheses")
def delivered_syntheses_fixture() -> list[dict[str, Any]]:
    """Return the published networks, once every tenant's build has finished.

    Sampling mid-build would fail on the timing rather than on the syntheses, so each tenant
    is given until the deadline to finish and only then read. A build that has recorded
    ``fail`` or ``timeout`` is finished: waiting cannot improve either and the tier should
    report it.
    """
    deadline = time.monotonic() + _BUILD_DEADLINE_SECONDS
    syntheses = _read_syntheses()
    while (not all(settled(synthesis["status"]) for synthesis in syntheses)
            and time.monotonic() < deadline):
        time.sleep(_BUILD_POLL_SECONDS)
        syntheses = _read_syntheses()
    return syntheses
