"""Layer 1 (contracts): cross-file consistency for the wan dispatcher stack.

The dispatcher stack couples to the shared common module (whose locals reference its
outputs) and to the storage stack's remote state (where it reads the store bucket).
Its output is wired to the dispatcher Lambda it declares, and it invokes the
synthesizer by the derived name from the common module (the synthesizer Lambda lives
in its own stack). These assert those couplings hold. No AWS calls.
"""
from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

WAN_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan"


def _stack_text() -> str:
    """Return the combined text of every ``.tf`` file in the wan stack."""
    return "".join(
        path.read_text(encoding="utf-8") for path in sorted(WAN_DIR.glob("*.tf"))
    )


def test_locals_reference_only_declared_common_outputs() -> None:
    """Every ``module.common.*`` reference resolves to a declared common output."""
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_remote_state_reads_the_storage_stack() -> None:
    """The stack reads the storage stack's state to learn the store bucket."""
    assert "common/storage/terraform.tfstate" in _stack_text()


def test_lambda_arn_output_references_the_declared_handler() -> None:
    """The ``lambda_function_arn`` output is wired to the declared handler."""
    outputs = output_values(WAN_DIR / "outputs.tf")
    assert "aws_lambda_function.handler" in str(outputs["lambda_function_arn"])


def test_dispatcher_invokes_the_derived_synthesizer_name() -> None:
    """The dispatcher derives the synthesizer function name from the common module."""
    assert "${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()


def test_dispatch_policy_targets_the_derived_synthesizer_arn() -> None:
    """The dispatch invoke policy targets the synthesizer's derived ARN, not a resource."""
    assert ":function:${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()
