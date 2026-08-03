"""Unit tests for loading a Python file as a module by its path.

A deployed Lambda's ``handler.py`` is the top-level module ``handler``, so the tests that
drive one load it by path rather than importing a package, and this is the function that
does it. Handing back the wrong file is the failure that costs most: every assertion after
it is about code the author did not write, and the report names the endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_module_utils import load_module_from_path


def test_the_module_loaded_is_the_file_at_the_path_given(lambdas_dir: Path) -> None:
    """What comes back is the code in that file, so its values are that file's values."""
    module = load_module_from_path("loaded_handler", lambdas_dir / "handler.py")
    assert module.HOME == str(lambdas_dir)


def test_the_module_carries_the_name_it_was_loaded_under(lambdas_dir: Path) -> None:
    """The name is the caller's to choose, which is how one file is loaded twice under two."""
    module = load_module_from_path("carriers_handler", lambdas_dir / "handler.py")
    assert module.__name__ == "carriers_handler"


def test_a_path_holding_no_file_is_reported(tmp_path: Path) -> None:
    """An absent handler raises rather than yielding an empty module that asserts to nothing."""
    with pytest.raises(FileNotFoundError):
        load_module_from_path("absent_handler", tmp_path / "handler.py")


def test_a_file_python_has_no_loader_for_is_refused(tmp_path: Path) -> None:
    """A suffix no import machinery claims yields no spec, and the load stops rather than guess."""
    (tmp_path / "handler.txt").write_text("MARK = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        load_module_from_path("not_python", tmp_path / "handler.txt")
