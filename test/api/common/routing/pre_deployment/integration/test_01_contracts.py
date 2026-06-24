"""Layer 1 (contracts): cross-file consistency for the routing stack.

The routing gateway couples to two other files: the shared common module (whose
outputs its locals reference) and the OpenAPI spec (whose handler placeholders it
fills via templatefile). These assert those couplings hold. No AWS calls.
"""
from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

ROUTING_DIR = REPO_ROOT / "src" / "api" / "common" / "routing"
OPENAPI_SPEC = REPO_ROOT / "src" / "www" / "api" / "openapi.json"


def _main_text() -> str:
    """Return the raw text of the routing stack's main.tf."""
    return (ROUTING_DIR / "main.tf").read_text(encoding="utf-8")


def test_locals_reference_only_declared_common_outputs() -> None:
    """Every ``module.common.*`` reference resolves to a declared common output."""
    refs = set(re.findall(r"module\.common\.(\w+)", _main_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_templatefile_provides_every_openapi_handler_placeholder() -> None:
    """Every ``${...HandlerArn}`` the OpenAPI spec needs is supplied by main.tf."""
    needed = set(re.findall(r"\$\{(\w+HandlerArn)\}",
                            OPENAPI_SPEC.read_text(encoding="utf-8")))
    supplied = set(re.findall(r"(\w+HandlerArn)\s*=", _main_text()))
    assert needed <= supplied


def test_api_id_output_references_the_declared_rest_api() -> None:
    """The ``api_gateway_id`` output is wired to the declared REST API."""
    outputs = output_values(ROUTING_DIR / "outputs.tf")
    assert "aws_api_gateway_rest_api.api" in str(outputs["api_gateway_id"])
