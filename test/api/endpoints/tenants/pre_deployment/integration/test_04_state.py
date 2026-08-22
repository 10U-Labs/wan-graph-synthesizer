from __future__ import annotations

import pytest

from repo_utils import REPO_ROOT
from test_terraform_drift import find_orphaned_resources, get_state_resources

TENANTS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants"


def _has_existing_state() -> bool:
    return bool(get_state_resources(TENANTS_DIR))


@pytest.mark.skipif(
    not _has_existing_state(),
    reason="Cold state - no prior OpenTofu state to validate against",
)
def test_no_orphaned_resources() -> None:
    assert not find_orphaned_resources(TENANTS_DIR)
