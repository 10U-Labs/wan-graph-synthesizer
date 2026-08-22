"""Unit tests for the check that every public definition under lib/python/ is used."""

from __future__ import annotations

from pathlib import Path

import pytest

from assert_python_definition_is_used import (
    main,
    named_elsewhere,
    public_definitions,
    python_files,
    unused_definitions,
)

MODULE = Path("lib", "python", "counting", "__init__.py")
SCRIPT = Path("scripts", "report.py")
OWN_TEST = Path("test", "lib", "python", "counting", "pre_deployment", "unit", "test_counting.py")
OWN_TESTS = Path("test", "lib", "python", "counting")
TREES = (Path("lib", "python"), Path("scripts"), Path("test"))
MODULE_SOURCE = '''"""Counting."""


class Tally:
    """A running total."""


def counted(items):
    """How many items there are."""
    return len(items)


def orphaned(items):
    """Nothing outside this file names it."""
    return items


def _private(items):
    """Not public."""
    return items


LIMIT = 3
'''
SCRIPT_SOURCE = '"""A script."""\n\nfrom counting import counted\n'
OWN_TEST_SOURCE = '"""Tests for counting."""\n\nfrom counting import Tally\n'


def _write(root: Path, relative: Path, text: str) -> None:
    """Write text to a file under root, making whatever directories it needs."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> Path:
    """One module, a script naming one definition, and a test naming another."""
    _write(root, MODULE, MODULE_SOURCE)
    _write(root, SCRIPT, SCRIPT_SOURCE)
    _write(root, OWN_TEST, OWN_TEST_SOURCE)
    return root


def test_python_files_reads_every_python_file_under_the_trees(tmp_path: Path) -> None:
    """Each .py file arrives keyed by its path relative to the repository root."""
    assert sorted(python_files(_repo(tmp_path), TREES)) == sorted([MODULE, SCRIPT, OWN_TEST])


def test_python_files_reads_nothing_from_a_tree_that_is_not_there(tmp_path: Path) -> None:
    """A tree the repository does not have contributes no files rather than failing."""
    assert not python_files(_repo(tmp_path), (Path("nowhere"),))


def test_public_definitions_finds_the_public_classes_and_functions(tmp_path: Path) -> None:
    """A private name and a plain assignment are both left out."""
    lines = python_files(_repo(tmp_path), TREES)[MODULE]
    assert public_definitions(lines) == [(4, "Tally"), (8, "counted"), (13, "orphaned")]


def test_named_elsewhere_finds_a_use_in_another_file(tmp_path: Path) -> None:
    """The script's import of counted is a use of it."""
    source = python_files(_repo(tmp_path), TREES)
    assert named_elsewhere("counted", source, (MODULE, 8), None) is True


def test_named_elsewhere_does_not_count_the_definition_itself(tmp_path: Path) -> None:
    """The line the definition is written on is not a use of it."""
    source = python_files(_repo(tmp_path), TREES)
    assert named_elsewhere("orphaned", source, (MODULE, 13), None) is False


def test_named_elsewhere_skips_a_use_under_the_skipped_directory(tmp_path: Path) -> None:
    """Tally is named by its own test and by nothing else, so skipping those loses it."""
    source = python_files(_repo(tmp_path), TREES)
    assert named_elsewhere("Tally", source, (MODULE, 4), OWN_TESTS) is False


def test_named_elsewhere_keeps_a_use_outside_the_skipped_directory(tmp_path: Path) -> None:
    """The script is not under the skipped directory, so its import still counts."""
    source = python_files(_repo(tmp_path), TREES)
    assert named_elsewhere("counted", source, (MODULE, 8), OWN_TESTS) is True


def test_unused_definitions_reports_what_nothing_names(tmp_path: Path) -> None:
    """Tally is kept by its own test and counted by the script, so only orphaned is left."""
    assert unused_definitions(_repo(tmp_path), False) == [(MODULE, 13, "orphaned")]


def test_unused_definitions_reports_what_only_its_own_tests_name(tmp_path: Path) -> None:
    """Asked to discount the module's own tests, Tally joins orphaned."""
    assert unused_definitions(_repo(tmp_path), True) == [
        (MODULE, 4, "Tally"),
        (MODULE, 13, "orphaned"),
    ]


def test_unused_definitions_reads_a_file_sitting_directly_in_lib_python(tmp_path: Path) -> None:
    """A file outside a module directory has no tests of its own to discount."""
    loose = Path("lib", "python", "loose.py")
    _write(_repo(tmp_path), loose, '"""Loose."""\n\n\ndef loose_end():\n    """Unused."""\n')
    assert unused_definitions(tmp_path, True) == [
        (MODULE, 4, "Tally"),
        (MODULE, 13, "orphaned"),
        (loose, 4, "loose_end"),
    ]


def test_main_answers_zero_when_every_definition_is_used(tmp_path: Path) -> None:
    """A module whose one definition the script imports leaves nothing to report."""
    _write(tmp_path, MODULE, '"""Counting."""\n\n\ndef counted(items):\n    """How many."""\n')
    _write(tmp_path, SCRIPT, SCRIPT_SOURCE)
    assert main(["--root", str(tmp_path)]) == 0


def test_main_answers_one_when_a_definition_is_unused(tmp_path: Path) -> None:
    """orphaned is unused, so the check fails the job it runs in."""
    assert main(["--root", str(_repo(tmp_path))]) == 1


def test_main_prints_an_annotation_naming_the_unused_definition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The annotation carries the file and line so GitHub marks the definition itself."""
    main(["--root", str(_repo(tmp_path))])
    assert f"::error file={MODULE},line=13::" in capsys.readouterr().out
