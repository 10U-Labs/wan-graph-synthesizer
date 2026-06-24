"""Unit tests for the common/routing stack's declared configuration.

Parse the stack's ``.tf`` with hcl2 and assert the regional REST API and its prod
stage are declared off the shared common module. No AWS calls, no apply.
"""
from __future__ import annotations

from typing import Any

from test_terraform_config import find_resource


def _resource(routing_main: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    """Return the body of a named resource of the given type, or fail."""
    body = find_resource(routing_main, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared in main.tf")
    return body


def _modules(routing_main: dict[str, object]) -> list[dict[str, Any]]:
    """Return the module blocks declared in main.tf."""
    blocks = routing_main.get("module", [])
    return blocks if isinstance(blocks, list) else []


def test_rest_api_is_declared(routing_main: dict[str, object]) -> None:
    """The REST API resource is declared."""
    assert find_resource(routing_main, "aws_api_gateway_rest_api", "api") is not None


def test_rest_api_has_the_product_name(routing_main: dict[str, object]) -> None:
    """The REST API carries the product's name."""
    api = _resource(routing_main, "aws_api_gateway_rest_api", "api")
    assert api["name"] == "wan-graph-synthesizer"


def test_rest_api_is_regional(routing_main: dict[str, object]) -> None:
    """The REST API uses a regional endpoint (CloudFront fronts it upstream)."""
    api = _resource(routing_main, "aws_api_gateway_rest_api", "api")
    assert api["endpoint_configuration"][0]["types"] == ["REGIONAL"]


def test_prod_stage_is_declared(routing_main: dict[str, object]) -> None:
    """The deployed stage is named ``prod``."""
    stage = _resource(routing_main, "aws_api_gateway_stage", "prod")
    assert stage["stage_name"] == "prod"


def test_deployment_is_declared(routing_main: dict[str, object]) -> None:
    """A deployment is declared for the stage to point at."""
    assert find_resource(routing_main, "aws_api_gateway_deployment", "prod") is not None


def test_common_module_is_sourced(routing_main: dict[str, object]) -> None:
    """The stack draws shared constants from the common module."""
    common = next(m["common"] for m in _modules(routing_main) if "common" in m)
    assert common["source"] == "../../../../lib/opentofu/common"
