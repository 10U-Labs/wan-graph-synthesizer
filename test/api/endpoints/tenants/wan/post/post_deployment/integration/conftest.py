"""Derived fixtures for the synthesizer post-deployment integration tier.

``synthesizer_config`` fetches the live synthesizer Lambda configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so the
existence, configuration, and wiring layers share the call. The synthesizer's name is
derived from the wan dispatcher name, matching the deploy-time derived name.

``delivered_designs`` goes a layer further and reads what the synthesizer published,
pairing each tenant's network with the demands its own config makes of it. The roster
in ``etc/`` is the list of tenants and ``seed`` supplies the file-stem-to-tenant-id
rule, so a tenant added to git is one this tier starts asking about with no edit here.
Each entry is a plain mapping of six keys: ``tenant``, the ``target_miles`` and
``seat_cap`` the config sets, the ``status`` document the GET passes through, and the
published ``backbone`` and ``demand`` collections that status can be measured against.
A tenant whose build is not ``ready`` has no network to read and carries both empty.
"""
from __future__ import annotations

import json
import time
from typing import Any, cast

import pytest
import yaml

import seed
from seed import _slug

# How long the published networks are given to catch up with the configs git holds, and
# how often they are asked. A tenant config change is delivered by the seed workflow, which
# runs independently of this one, so a push that touches both arrives here with a rebuild
# either in flight or not yet started. Waiting turns that race into a bounded contract --
# the store settles on the configuration within the deadline -- rather than a coin flip on
# which workflow reached its last job first. A build of the largest tenant takes minutes.
_SETTLE_DEADLINE_SECONDS = 900
_SETTLE_POLL_SECONDS = 20


def _stored(client: Any, bucket: str, key: str) -> Any:
    """Decode a JSON document the synthesizer published to the store."""
    return json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read())


def _roster() -> dict[str, dict[str, Any]]:
    """Each tenant id the roster declares, with the whole config git holds for it."""
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(seed.ETC.glob("*.yml"))
    }


@pytest.fixture(name="store_bucket_name")
def store_bucket_name_fixture(synthesizer_config: dict[str, Any]) -> str:
    """Return the store bucket the live synthesizer publishes to.

    Read off the running function rather than from the OpenTofu, so this tier reads the
    bucket the synthesizer actually writes to and not the one it was declared to.
    """
    variables = cast("dict[str, Any]", synthesizer_config["Environment"])["Variables"]
    return str(variables["STORE_BUCKET"])


def _read_designs(client: Any, bucket: str) -> list[dict[str, Any]]:
    """Every declared tenant's published network beside the demands its config makes of it.

    A tenant whose build did not finish has no ``wan.json`` at all, so its collections come
    back empty rather than read: the first test in the layer is then the one that reports
    it, instead of every test in the layer dying inside a fixture.
    """
    designs: list[dict[str, Any]] = []
    for tenant, config in _roster().items():
        status = _stored(client, bucket, f"tenants/{tenant}/wan-status.json")
        published = (
            _stored(client, bucket, f"tenants/{tenant}/wan.json")
            if status.get("status") == "ready"
            else {}
        )
        backbone = config["backbone"]
        designs.append({
            "tenant": tenant,
            "target_miles": backbone["coverage_target_miles"],
            "max_path_stretch": backbone["max_path_stretch"],
            "seat_cap": backbone["node_count"]["max"],
            "status": status,
            "backbone": published.get("backbone-nodes", []),
            "demand": published.get("tenant-nodes", []) + published.get("provider-nodes", []),
            "links": published.get("backbone-links", []),
        })
    return designs


def _settled(design: dict[str, Any]) -> bool:
    """True once a tenant's published network is one built to the requirements git now holds.

    Two things make a design unsettled, and both mean a rebuild is owed rather than that
    anything is wrong: the build is still running, or it finished against requirements the
    config has since moved off. Either resolves on its own once the seed workflow has run.

    Both requirements the published status echoes are checked, not just the coverage
    target. A design built before the stretch bound was configured carries no bound at all
    and one built before the operator moved it carries the old one; either way its links
    were routed under a rule this layer is no longer measuring it by, and reading it would
    report a violation where the truth is a rebuild that has not happened yet.
    """
    status = design["status"]
    coverage = status.get("coverage")
    if status.get("status") != "ready" or coverage is None:
        return bool(status.get("status") == "failed")
    return bool(
        coverage["target_miles"] == design["target_miles"]
        and status.get("max_path_stretch") == design["max_path_stretch"]
    )


@pytest.fixture(name="delivered_designs")
def delivered_designs_fixture(
        s3_client: Any, store_bucket_name: str) -> list[dict[str, Any]]:
    """Return the published networks, once the store has caught up with the configs.

    The configs are delivered by the seed workflow and this one runs independently of it,
    so a push that touches both reaches here with rebuilds in flight or not yet begun.
    Sampling that moment would fail on the timing rather than on the designs, so the store
    is given until the deadline to settle and only then read. A build that has recorded
    ``failed`` is settled: waiting cannot improve it and the layer should report it.
    """
    deadline = time.monotonic() + _SETTLE_DEADLINE_SECONDS
    designs = _read_designs(s3_client, store_bucket_name)
    while not all(map(_settled, designs)) and time.monotonic() < deadline:
        time.sleep(_SETTLE_POLL_SECONDS)
        designs = _read_designs(s3_client, store_bucket_name)
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
