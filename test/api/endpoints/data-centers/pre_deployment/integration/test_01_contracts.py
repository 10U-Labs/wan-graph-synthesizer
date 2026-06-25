"""Layer 1 (contracts): cross-file consistency for the data-centers stack.

The data-centers stack couples to the shared common module (whose outputs its
locals reference) and to the storage stack's remote state (where it reads the
store bucket). These assert those couplings hold. No AWS calls.
"""
from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import COMMON_OUTPUTS_FILE, output_values

DATA_CENTERS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "data-centers"


def _stack_text() -> str:
    """Return the combined text of the data-centers stack's main.tf and iam.tf."""
    return ((DATA_CENTERS_DIR / "main.tf").read_text(encoding="utf-8")
            + (DATA_CENTERS_DIR / "iam.tf").read_text(encoding="utf-8"))


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
    outputs = output_values(DATA_CENTERS_DIR / "outputs.tf")
    assert "aws_lambda_function.handler" in str(outputs["lambda_function_arn"])
