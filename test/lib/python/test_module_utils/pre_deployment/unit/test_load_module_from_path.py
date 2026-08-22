from __future__ import annotations

from pathlib import Path

import pytest

from test_module_utils import load_module_from_path


def test_the_module_loaded_is_the_file_at_the_path_given(lambdas_dir: Path) -> None:
    module = load_module_from_path("loaded_handler", lambdas_dir / "handler.py")
    assert module.HOME == str(lambdas_dir)


def test_the_module_carries_the_name_it_was_loaded_under(lambdas_dir: Path) -> None:
    module = load_module_from_path("carriers_handler", lambdas_dir / "handler.py")
    assert module.__name__ == "carriers_handler"


def test_a_path_holding_no_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_module_from_path("absent_handler", tmp_path / "handler.py")


def test_a_file_python_has_no_loader_for_is_refused(tmp_path: Path) -> None:
    (tmp_path / "handler.txt").write_text("MARK = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        load_module_from_path("not_python", tmp_path / "handler.txt")
