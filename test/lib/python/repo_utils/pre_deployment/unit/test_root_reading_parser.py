from __future__ import annotations

from pathlib import Path

from repo_utils import REPO_ROOT, root_reading_parser


def test_the_parser_defaults_to_the_repository_this_file_sits_in() -> None:
    assert root_reading_parser("why").parse_args([]).root == REPO_ROOT


def test_the_parser_reads_a_root_named_on_the_command_line() -> None:
    assert root_reading_parser("why").parse_args(["--root", "/tmp/x"]).root == Path("/tmp/x")


def test_the_parser_carries_the_description_it_was_given() -> None:
    assert root_reading_parser("why this runs").description == "why this runs"
