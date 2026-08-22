from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def lambdas_dir(tmp_path: Path) -> Path:
    (tmp_path / "handler.py").write_text(f'HOME = r"{tmp_path}"\n', encoding="utf-8")
    return tmp_path
