from __future__ import annotations

import sys
from pathlib import Path

import pytest

from test_module_utils import create_lambda_loader


def test_the_file_named_is_read_from_the_lambdas_directory(lambdas_dir: Path) -> None:
    module = create_lambda_loader(lambdas_dir)("handler.py", "endpoint_handler")
    assert module.HOME == str(lambdas_dir)


def test_the_module_is_named_by_the_caller_not_by_the_filename(lambdas_dir: Path) -> None:
    module = create_lambda_loader(lambdas_dir)("handler.py", "tenants_handler")
    assert module.__name__ == "tenants_handler"


def test_the_lambdas_directory_goes_on_the_import_path(
        lambdas_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", [*sys.path])
    create_lambda_loader(lambdas_dir)("handler.py", "endpoint_handler")
    assert sys.path[0] == str(lambdas_dir)


def test_a_directory_already_on_the_import_path_is_not_added_again(
        lambdas_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", [*sys.path])
    load_lambda_module = create_lambda_loader(lambdas_dir)
    load_lambda_module("handler.py", "first_handler")
    load_lambda_module("handler.py", "second_handler")
    assert sys.path.count(str(lambdas_dir)) == 1
