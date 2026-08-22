from pathlib import Path


def _find_repo_root_from_path(start_path: Path) -> Path:
    for parent in [start_path] + list(start_path.parents):
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def find_repo_root() -> Path:
    return _find_repo_root_from_path(Path(__file__).resolve())


REPO_ROOT = find_repo_root()
