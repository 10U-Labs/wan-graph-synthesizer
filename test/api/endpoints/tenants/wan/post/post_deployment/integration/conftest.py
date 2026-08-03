"""Derived fixtures for the synthesizer post-deployment integration tier.

``synthesizer_config`` fetches the live synthesizer Lambda configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so the
existence, configuration, and wiring layers share the call. The synthesizer's name is
derived from the wan dispatcher name, matching the deploy-time derived name.

``delivered_designs`` goes a layer further and reads what the synthesizer published,
pairing each tenant's network with the demands its own config makes of it. The roster
in ``etc/`` is the list of tenants and ``seed`` supplies the file-stem-to-tenant-id
rule, so a tenant added to git is one this tier starts asking about with no edit here.
The reading itself is ``test_published_designs.published_design``, which asks the API
for each tenant's build state and its four published collections; nothing here opens the
store the synthesizer writes to. Each entry is a plain mapping of nine keys: ``tenant``,
the ``target_miles``, ``max_path_stretch``, ``seat_cap`` and pinned ``forced`` cities the
config sets, the ``status`` document the GET passes through, and the published
``backbone``, ``demand`` and ``links`` collections that status can be measured against.
A tenant whose build is not ``ready`` has no network to read and carries all three empty.
"""
from __future__ import annotations

import time
from typing import Any, cast

import pytest
import yaml

import seed
from seed import DEFAULT_API, _slug
from test_published_designs import published_design, settled

# How long the tenants are given to finish building, and how often they are asked. The
# builds are started by the ``seeding`` job in .github/workflows/seed.yml, which the one
# test file that uses this fixture runs after: the POST that starts a build records
# ``creating`` before it answers, so by the time seeding returns every tenant is at
# ``creating`` or later and there is no earlier build left to mistake for the current one.
# Waiting for the state to leave ``creating`` and ``building`` is then the whole of the
# question (GitHub issue #47).
_BUILD_DEADLINE_SECONDS = 900
_BUILD_POLL_SECONDS = 20


def _roster() -> dict[str, dict[str, Any]]:
    """Each tenant id the roster declares, with the whole config git holds for it."""
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(seed.ETC.glob("*.yml"))
    }


def _read_designs() -> list[dict[str, Any]]:
    """Every declared tenant's published network beside the demands its config makes of it."""
    return [
        published_design(DEFAULT_API, tenant, config)
        for tenant, config in _roster().items()
    ]


@pytest.fixture(name="delivered_designs")
def delivered_designs_fixture() -> list[dict[str, Any]]:
    """Return the published networks, once every tenant's build has finished.

    Sampling mid-build would fail on the timing rather than on the designs, so each tenant
    is given until the deadline to finish and only then read. A build that has recorded
    ``failed`` is finished: waiting cannot improve it and the layer should report it.
    """
    deadline = time.monotonic() + _BUILD_DEADLINE_SECONDS
    designs = _read_designs()
    while (not all(settled(design["status"]) for design in designs)
            and time.monotonic() < deadline):
        time.sleep(_BUILD_POLL_SECONDS)
        designs = _read_designs()
    return designs


@pytest.fixture(name="synthesizer_function_name")
def synthesizer_function_name_fixture(function_name: str) -> str:
    """Return the deterministic synthesizer Lambda name."""
    return f"{function_name}-synthesizer"


@pytest.fixture(name="synthesizer_role_name")
def synthesizer_role_name_fixture() -> str:
    """Return the synthesizer Lambda's dedicated execution role name."""
    return "wan-graph-synthesizer-synthesizer"


@pytest.fixture(name="synthesizer_config")
def synthesizer_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response["Configuration"])


@pytest.fixture(name="synthesizer_invoke_config")
def synthesizer_invoke_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer's async (event) invocation config."""
    response = lambda_client.get_function_event_invoke_config(
        FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response)


@pytest.fixture(name="failure_handler_function_name")
def failure_handler_function_name_fixture(function_name: str) -> str:
    """Return the deterministic failure-handler Lambda name."""
    return f"{function_name}-failure-handler"


@pytest.fixture(name="failure_handler_role_name")
def failure_handler_role_name_fixture() -> str:
    """Return the failure handler's dedicated execution role name."""
    return "wan-graph-synthesizer-failure-handler"


@pytest.fixture(name="failure_handler_config")
def failure_handler_config_fixture(
        lambda_client: Any, failure_handler_function_name: str) -> dict[str, Any]:
    """Return the live failure-handler Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=failure_handler_function_name)
    return cast("dict[str, Any]", response["Configuration"])
