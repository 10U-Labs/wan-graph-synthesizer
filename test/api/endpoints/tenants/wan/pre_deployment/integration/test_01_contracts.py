from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

WAN_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan"


def _stack_text() -> str:
    return "".join(
        path.read_text(encoding="utf-8") for path in sorted(WAN_DIR.glob("*.tf"))
    )


def test_locals_reference_only_declared_common_outputs() -> None:
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_remote_state_reads_the_storage_stack() -> None:
    assert "common/storage/terraform.tfstate" in _stack_text()


def test_lambda_arn_output_references_the_declared_handler() -> None:
    outputs = output_values(WAN_DIR / "outputs.tf")
    assert "aws_lambda_function.handler" in str(outputs["lambda_function_arn"])


def test_dispatcher_invokes_the_derived_synthesizer_name() -> None:
    assert "${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()


def test_dispatch_policy_targets_the_derived_synthesizer_arn() -> None:
    assert ":function:${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()
