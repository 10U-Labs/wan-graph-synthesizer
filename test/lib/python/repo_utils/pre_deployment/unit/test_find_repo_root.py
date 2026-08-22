from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import _find_repo_root_from_path, find_repo_root


def test_a_directory_holding_a_git_directory_is_its_own_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _find_repo_root_from_path(tmp_path) == tmp_path


def test_a_file_deep_in_a_checkout_resolves_to_the_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "test" / "lib" / "python"
    nested.mkdir(parents=True)
    assert _find_repo_root_from_path(nested / "conftest.py") == tmp_path


def test_a_linked_worktree_is_a_checkout_too(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")
    assert _find_repo_root_from_path(tmp_path) == tmp_path


def test_the_nearest_checkout_wins_over_one_further_up(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "vendor" / "other-repo"
    (inner / ".git").mkdir(parents=True)
    assert _find_repo_root_from_path(inner / "setup.py") == inner


def test_a_path_with_no_checkout_above_it_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Could not find repository root"):
        _find_repo_root_from_path(tmp_path / "no" / "checkout" / "here")


def test_the_root_found_for_this_module_is_the_checkout_it_lives_in() -> None:
    assert find_repo_root() == Path(__file__).resolve().parents[6]
