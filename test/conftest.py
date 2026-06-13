"""Shared pytest fixtures and import path setup for the WAN designer tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEST_DIR = REPO_ROOT / "test"

for candidate in (REPO_ROOT, SCRIPTS_DIR, TEST_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
