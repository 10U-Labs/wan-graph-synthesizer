from __future__ import annotations

import ast
import bisect
import io
import tokenize
from pathlib import Path
from typing import Callable

import yaml

from repo_utils import root_reading_parser

TREES = (
    Path(".github", "workflows"),
    Path("etc"),
    Path("lib"),
    Path("scripts"),
    Path("src"),
    Path("test"),
)
VENDORED = Path("src", "www", "spa", "vendor")
DEFINITIONS = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Module)
OPENS_A_PATTERN = "(,=:[!&|?{};+-*%~^<>"


def _lines_of(text: str, places: list[int]) -> list[int]:
    breaks = [place for place, character in enumerate(text) if character == "\n"]
    return sorted({bisect.bisect_right(breaks, place) + 1 for place in places})


def _past_quoted(text: str, place: int) -> int:
    quote = text[place]
    place += 1
    while place < len(text):
        if text[place] == "\\":
            place += 2
        elif text[place] == quote:
            return place + 1
        else:
            place += 1
    return place


def _past_line(text: str, place: int) -> int:
    end = text.find("\n", place)
    return len(text) if end < 0 else end


def _past_block(text: str, place: int, closing: str) -> int:
    end = text.find(closing, place + len(closing))
    return len(text) if end < 0 else end + len(closing)


def _opens_a_pattern(text: str, place: int) -> bool:
    before = text[:place].rstrip()
    return not before or before[-1] in OPENS_A_PATTERN or before.endswith("return")


def _past_pattern(text: str, place: int) -> int:
    place += 1
    inside_a_class = False
    while place < len(text):
        character = text[place]
        if character == "\\":
            place += 2
        elif character == "\n":
            return place
        elif character == "[":
            inside_a_class = True
            place += 1
        elif character == "]":
            inside_a_class = False
            place += 1
        elif character == "/" and not inside_a_class:
            return place + 1
        else:
            place += 1
    return place


def marked_comments(
    text: str,
    quotes: str,
    line_markers: tuple[str, ...],
    block: tuple[str, str],
    patterns: bool,
) -> list[int]:
    places: list[int] = []
    place = 0
    while place < len(text):
        character = text[place]
        if character in quotes:
            place = _past_quoted(text, place)
        elif any(text.startswith(marker, place) for marker in line_markers):
            places.append(place)
            place = _past_line(text, place)
        elif text.startswith(block[0], place):
            places.append(place)
            place = _past_block(text, place, block[1])
        elif patterns and character == "/" and _opens_a_pattern(text, place):
            place = _past_pattern(text, place)
        else:
            place += 1
    return _lines_of(text, places)


def hcl_comments(text: str) -> list[int]:
    return marked_comments(text, '"', ("#", "//"), ("/*", "*/"), False)


def javascript_comments(text: str) -> list[int]:
    return marked_comments(text, "\"'`", ("//",), ("/*", "*/"), True)


def python_comments(text: str) -> list[int]:
    places = [
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, DEFINITIONS) or not node.body:
            continue
        opening = node.body[0]
        if isinstance(opening, ast.Expr) and isinstance(opening.value, ast.Constant):
            if isinstance(opening.value.value, str):
                places.append(opening.lineno)
    return sorted(set(places))


def yaml_comments(text: str) -> list[int]:
    covered = bytearray(len(text))
    for token in yaml.scan(text):
        for place in range(token.start_mark.index, token.end_mark.index):
            covered[place] = 1
    return _lines_of(
        text,
        [
            place
            for place, seen in enumerate(covered)
            if not seen and not text[place].isspace()
        ],
    )


READERS: dict[str, Callable[[str], list[int]]] = {
    ".js": javascript_comments,
    ".py": python_comments,
    ".tf": hcl_comments,
    ".yml": yaml_comments,
}


def commented_files(root: Path) -> list[tuple[Path, int]]:
    found: list[tuple[Path, int]] = []
    for tree in TREES:
        for path in sorted((root / tree).rglob("*")):
            relative = path.relative_to(root)
            reader = READERS.get(path.suffix)
            if reader is None or not path.is_file() or VENDORED in relative.parents:
                continue
            found.extend(
                (relative, line) for line in reader(path.read_text(encoding="utf-8"))
            )
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = root_reading_parser(
        "Assert nothing this repository publishes carries a comment."
    )
    arguments = parser.parse_args(argv)
    found = commented_files(arguments.root)
    for path, line in found:
        print(
            f"::error file={path},line={line}::{path}:{line} carries a comment"
            f" or a docstring; delete it and let the code say what it does"
        )
    return 1 if found else 0
