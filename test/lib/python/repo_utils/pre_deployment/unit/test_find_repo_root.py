"""Unit tests for the walk that finds the checkout a test is running inside.

Thirty-five files under ``test/`` build a path out of ``repo_utils.REPO_ROOT``: the
OpenTofu stack directory a drift check runs ``tofu plan`` in, the ``handler.py`` a unit
test loads, the ``etc/`` config a seed run delivers. A walk that stops one directory
short hands every one of them a path that is perfectly well formed and holds nothing,
and each then reports its own subject missing rather than the walk that mislaid it.

The walk is given its start path here rather than taking it from ``__file__``, so the
trees it is asked about are built for the case and no answer depends on where the
checkout happens to sit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import _find_repo_root_from_path, find_repo_root


def test_a_directory_holding_a_git_directory_is_its_own_root(tmp_path: Path) -> None:
    """The start path is considered before any parent of it, so a checkout root is itself."""
    (tmp_path / ".git").mkdir()
    assert _find_repo_root_from_path(tmp_path) == tmp_path


def test_a_file_deep_in_a_checkout_resolves_to_the_checkout(tmp_path: Path) -> None:
    """A path several directories down finds the checkout above it and not a step of the way."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "test" / "lib" / "python"
    nested.mkdir(parents=True)
    assert _find_repo_root_from_path(nested / "conftest.py") == tmp_path


def test_a_linked_worktree_is_a_checkout_too(tmp_path: Path) -> None:
    """A worktree records ``.git`` as a file naming the real one, and that marks a root too."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")
    assert _find_repo_root_from_path(tmp_path) == tmp_path


def test_the_nearest_checkout_wins_over_one_further_up(tmp_path: Path) -> None:
    """A checkout inside another answers for its own files, so vendored trees stay apart."""
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "vendor" / "other-repo"
    (inner / ".git").mkdir(parents=True)
    assert _find_repo_root_from_path(inner / "setup.py") == inner


def test_a_path_with_no_checkout_above_it_is_refused(tmp_path: Path) -> None:
    """Nothing is invented for a path outside every checkout; the walk says so and stops."""
    with pytest.raises(RuntimeError, match="Could not find repository root"):
        _find_repo_root_from_path(tmp_path / "no" / "checkout" / "here")


def test_the_root_found_for_this_module_is_the_checkout_it_lives_in() -> None:
    """``find_repo_root`` answers for the installed copy, six directories above this file."""
    assert find_repo_root() == Path(__file__).resolve().parents[6]
