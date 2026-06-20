"""Repository path utilities for tests (mirrors 10ulabs.com/lib/python/repo_utils)."""

from pathlib import Path


def _find_repo_root_from_path(start_path: Path) -> Path:
    """Find the repository root (the directory containing .git) from a start path."""
    for parent in [start_path] + list(start_path.parents):
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def find_repo_root() -> Path:
    """Find the repository root by looking for the .git directory."""
    return _find_repo_root_from_path(Path(__file__).resolve())


REPO_ROOT = find_repo_root()
