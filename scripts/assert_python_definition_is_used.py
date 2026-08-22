from __future__ import annotations

import ast
import re
from pathlib import Path

from repo_utils import root_reading_parser

MODULES = Path("lib", "python")
TREES = (Path("lib", "python"), Path("scripts"), Path("test"))
DEFINITIONS = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)


def python_files(root: Path, trees: tuple[Path, ...]) -> dict[Path, list[str]]:
    read: dict[Path, list[str]] = {}
    for tree in trees:
        for path in sorted((root / tree).rglob("*.py")):
            read[path.relative_to(root)] = path.read_text(encoding="utf-8").splitlines()
    return read


def public_definitions(lines: list[str]) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.name)
        for node in ast.parse("\n".join(lines)).body
        if isinstance(node, DEFINITIONS) and not node.name.startswith("_")
    ]


def named_elsewhere(
    name: str,
    source: dict[Path, list[str]],
    written: tuple[Path, int],
    skipped: Path | None,
) -> bool:
    word = re.compile(r"\b" + re.escape(name) + r"\b")
    for other, lines in source.items():
        if skipped is not None and skipped in other.parents:
            continue
        for number, line in enumerate(lines, 1):
            if (other, number) == written:
                continue
            if word.search(line):
                return True
    return False


def unused_definitions(root: Path, outside_own_tests: bool) -> list[tuple[Path, int, str]]:
    source = python_files(root, TREES)
    unused: list[tuple[Path, int, str]] = []
    for path, lines in source.items():
        if MODULES not in path.parents:
            continue
        skipped = None
        if outside_own_tests and len(path.parts) > len(MODULES.parts) + 1:
            skipped = Path("test", *path.parts[: len(MODULES.parts) + 1])
        for lineno, name in public_definitions(lines):
            if not named_elsewhere(name, source, (path, lineno), skipped):
                unused.append((path, lineno, name))
    return sorted(unused)


def main(argv: list[str] | None = None) -> int:
    parser = root_reading_parser(
        "Assert every public definition under lib/python/ is used."
    )
    parser.add_argument(
        "--outside-own-tests",
        action="store_true",
        help="Do not count a use in the module's own directory under test/lib/python/.",
    )
    arguments = parser.parse_args(argv)
    unused = unused_definitions(arguments.root, arguments.outside_own_tests)
    for path, lineno, name in unused:
        print(
            f"::error file={path},line={lineno}::{path}:{lineno} defines {name}"
            f" and nothing outside it uses it; delete it or use it"
        )
    return 1 if unused else 0
