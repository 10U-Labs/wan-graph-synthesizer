from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

ROUTING_DIR = REPO_ROOT / "src" / "api" / "common" / "routing"
OPENAPI_SPEC = REPO_ROOT / "src" / "www" / "api" / "openapi.json"


def _main_text() -> str:
    return (ROUTING_DIR / "main.tf").read_text(encoding="utf-8")


def test_locals_reference_only_declared_common_outputs() -> None:
    refs = set(re.findall(r"module\.common\.(\w+)", _main_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_templatefile_provides_every_openapi_handler_placeholder() -> None:
    needed = set(re.findall(r"\$\{(\w+HandlerArn)\}",
                            OPENAPI_SPEC.read_text(encoding="utf-8")))
    supplied = set(re.findall(r"(\w+HandlerArn)\s*=", _main_text()))
    assert needed <= supplied


def test_templatefile_supplies_no_placeholder_the_spec_does_not_need() -> None:
    needed = set(re.findall(r"\$\{(\w+HandlerArn)\}",
                            OPENAPI_SPEC.read_text(encoding="utf-8")))
    supplied = set(re.findall(r"(\w+HandlerArn)\s*=", _main_text()))
    assert supplied <= needed


def test_api_id_output_references_the_declared_rest_api() -> None:
    outputs = output_values(ROUTING_DIR / "outputs.tf")
    assert "aws_api_gateway_rest_api.api" in str(outputs["api_gateway_id"])
