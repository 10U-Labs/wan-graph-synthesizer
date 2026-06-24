"""Layer 4 (state): the declared csps state matches AWS reality.

Run ``tofu plan`` and confirm nothing it would create already exists in AWS
outside of state. Skipped on a cold stack with no prior state.
"""
from __future__ import annotations

import pytest

from repo_utils import REPO_ROOT
from test_terraform_drift import find_orphaned_resources, get_state_resources

CSPS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "csps"


def _has_existing_state() -> bool:
    """Report whether the stack already has resources tracked in state."""
    return bool(get_state_resources(CSPS_DIR))


@pytest.mark.skipif(
    not _has_existing_state(),
    reason="Cold state - no prior OpenTofu state to validate against",
)
def test_no_orphaned_resources() -> None:
    """No resource the stack would create already exists unmanaged in AWS."""
    assert not find_orphaned_resources(CSPS_DIR)
