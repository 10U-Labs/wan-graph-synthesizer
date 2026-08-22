from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

SYNTH_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan" / "post"


def _stack_text() -> str:
    return "".join(
        path.read_text(encoding="utf-8") for path in sorted(SYNTH_DIR.glob("*.tf"))
    )


def test_locals_reference_only_declared_common_outputs() -> None:
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_remote_state_reads_the_storage_stack() -> None:
    assert "common/storage/terraform.tfstate" in _stack_text()


def test_function_arn_output_references_the_synthesizer() -> None:
    outputs = output_values(SYNTH_DIR / "outputs.tf")
    assert "aws_lambda_function.synthesizer" in str(outputs["synthesizer_function_arn"])


def test_function_name_is_derived_from_the_common_module() -> None:
    assert "${module.common.lambda_handler_names.wan}-synthesizer" in _stack_text()
