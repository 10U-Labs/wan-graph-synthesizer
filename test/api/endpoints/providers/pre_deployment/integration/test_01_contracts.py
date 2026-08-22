from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

PROVIDERS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "providers"


def _stack_text() -> str:
    return ((PROVIDERS_DIR / "main.tf").read_text(encoding="utf-8")
            + (PROVIDERS_DIR / "iam.tf").read_text(encoding="utf-8"))


def test_locals_reference_only_declared_common_outputs() -> None:
    refs = set(re.findall(r"module\.common\.(\w+)", _stack_text()))
    declared = set(output_values(COMMON_OUTPUTS_FILE))
    assert refs <= declared


def test_remote_state_reads_the_storage_stack() -> None:
    assert "common/storage/terraform.tfstate" in _stack_text()


def test_lambda_arn_output_references_the_declared_handler() -> None:
    outputs = output_values(PROVIDERS_DIR / "outputs.tf")
    assert "aws_lambda_function.handler" in str(outputs["lambda_function_arn"])
