from __future__ import annotations

import argparse
from pathlib import Path


def _find_repo_root_from_path(start_path: Path) -> Path:
    for parent in [start_path] + list(start_path.parents):
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def find_repo_root() -> Path:
    return _find_repo_root_from_path(Path(__file__).resolve())


REPO_ROOT = find_repo_root()


def root_reading_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--root",
        default=REPO_ROOT,
        type=Path,
        help="The repository root to read (default: the one this file sits in).",
    )
    return parser
