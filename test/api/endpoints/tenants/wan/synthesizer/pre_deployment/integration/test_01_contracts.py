"""Layer 1 (contracts): cross-file consistency for the synthesizer stack.

The synthesizer stack couples to the shared common module (whose locals reference its
outputs) and to the storage stack's remote state (where it reads the store bucket). Its
output is wired to the synthesizer Lambda it declares, whose function name is derived
from the common module (so the sibling dispatcher can invoke it by the same derived
name). These assert those couplings hold. No AWS calls.
"""
from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

SYNTH_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan" / "synthesizer"


def _stack_text() -> str:
    """Return the combined text of every ``.tf`` file in the synthesizer stack."""
    return "".join(
        path.read_text(encoding="utf-8") for path in sorted(SYNTH_DIR.glob("*.tf"))
    )


def test_locals_reference_only_declared_common_outputs() -> None:
    """Every ``module.common.*`` reference resolves to a declared common output."""
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_remote_state_reads_the_storage_stack() -> None:
    """The stack reads the storage stack's state to learn the store bucket."""
    assert "common/storage/terraform.tfstate" in _stack_text()


def test_function_arn_output_references_the_synthesizer() -> None:
    """The ``synthesizer_function_arn`` output is wired to the declared synthesizer Lambda."""
    outputs = output_values(SYNTH_DIR / "outputs.tf")
    assert "aws_lambda_function.synthesizer" in str(outputs["synthesizer_function_arn"])


def test_function_name_is_derived_from_the_common_module() -> None:
    """The synthesizer's function name is derived from the shared common module name."""
    assert "${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()
