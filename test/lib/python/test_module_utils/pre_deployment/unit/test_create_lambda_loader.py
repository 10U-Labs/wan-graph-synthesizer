"""Unit tests for the loader that reads a handler out of one lambdas directory.

A handler file deployed to Lambda sits beside whatever it imports, and the runtime puts
that directory on the import path before running it. This loader reproduces both halves,
so a test drives the same file the same way the deployment does. Leaving the directory off
the path fails the import inside the handler, which reads as a broken handler rather than
as a loader that did not finish setting the stage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from test_module_utils import create_lambda_loader


def test_the_file_named_is_read_from_the_lambdas_directory(lambdas_dir: Path) -> None:
    """The loader is told a filename, and the directory it was built for supplies the rest."""
    module = create_lambda_loader(lambdas_dir)("handler.py", "endpoint_handler")
    assert module.HOME == str(lambdas_dir)


def test_the_module_is_named_by_the_caller_not_by_the_filename(lambdas_dir: Path) -> None:
    """Two endpoints keep two ``handler.py`` files apart by loading each under its own name."""
    module = create_lambda_loader(lambdas_dir)("handler.py", "tenants_handler")
    assert module.__name__ == "tenants_handler"


def test_the_lambdas_directory_goes_on_the_import_path(
        lambdas_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A handler imports its siblings by bare name, so its own directory has to be reachable."""
    monkeypatch.setattr(sys, "path", [*sys.path])
    create_lambda_loader(lambdas_dir)("handler.py", "endpoint_handler")
    assert sys.path[0] == str(lambdas_dir)


def test_a_directory_already_on_the_import_path_is_not_added_again(
        lambdas_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loading twice leaves one entry, so a suite of many cases does not grow the path."""
    monkeypatch.setattr(sys, "path", [*sys.path])
    load_lambda_module = create_lambda_loader(lambdas_dir)
    load_lambda_module("handler.py", "first_handler")
    load_lambda_module("handler.py", "second_handler")
    assert sys.path.count(str(lambdas_dir)) == 1
