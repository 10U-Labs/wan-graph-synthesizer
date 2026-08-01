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
from typing import Any, cast

import pytest
import yaml

import seed
from seed import _slug


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


@pytest.fixture(name="delivered_designs")
def delivered_designs_fixture(
        s3_client: Any, store_bucket_name: str) -> list[dict[str, Any]]:
    """Return every declared tenant's published network beside its config's demands.

    A tenant whose build did not finish has no ``wan.json`` at all, so its collections are
    left empty rather than read: the first test in the layer is then the one that reports
    it, instead of every test in the layer dying inside this fixture.
    """
    designs: list[dict[str, Any]] = []
    for tenant, config in _roster().items():
        status = _stored(
            s3_client, store_bucket_name, f"tenants/{tenant}/wan-status.json")
        published = (
            _stored(s3_client, store_bucket_name, f"tenants/{tenant}/wan.json")
            if status.get("status") == "ready"
            else {}
        )
        backbone = config["backbone"]
        designs.append({
            "tenant": tenant,
            "target_miles": backbone["coverage_target_miles"],
            "seat_cap": backbone["node_count"]["max"],
            "status": status,
            "backbone": published.get("backbone-nodes", []),
            "demand": published.get("tenant-nodes", []) + published.get("provider-nodes", []),
        })
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
