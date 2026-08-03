"""A directory laid out the way a deployed Lambda's is, for the loader tests to read.

Both loaders take a file rather than a package, so what they need to be pointed at is a
directory holding one ``handler.py``. It is built here once instead of in each test file,
and the module it holds records the directory it was written into, so a test can say
which file it was handed rather than merely that it was handed one.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def lambdas_dir(tmp_path: Path) -> Path:
    """A lambdas directory holding a ``handler.py`` that names where it came from."""
    (tmp_path / "handler.py").write_text(f'HOME = r"{tmp_path}"\n', encoding="utf-8")
    return tmp_path
