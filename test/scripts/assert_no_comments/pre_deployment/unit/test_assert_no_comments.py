from __future__ import annotations

from pathlib import Path

import pytest

from assert_no_comments import (
    commented_files,
    hcl_comments,
    javascript_comments,
    main,
    python_comments,
    yaml_comments,
)

SOURCE = Path("src", "counting.py")
VENDORED = Path("src", "www", "spa", "vendor", "leaflet.js")
PROSE = Path("src", "notes.md")


def _write(root: Path, relative: Path, text: str) -> None:
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_text(text, encoding="utf-8")


def _repo(root: Path) -> Path:
    _write(root, SOURCE, "x = 1\ny = 2\nz = 3\n")
    _write(root, VENDORED, "// somebody else wrote this\n")
    _write(root, PROSE, "A paragraph explaining nothing in particular.\n")
    return root


def test_a_python_comment_on_a_line_of_its_own_is_reported() -> None:
    assert python_comments("# one\nx = 1\n") == [1]


def test_a_python_comment_after_code_on_the_same_line_is_reported() -> None:
    assert python_comments("x = 1\ny = 2  # two\n") == [2]


def test_a_hash_inside_a_python_string_is_not_reported() -> None:
    assert python_comments('x = "# not a comment"\n') == []


def test_a_python_module_docstring_is_reported() -> None:
    assert python_comments('"""What this module is for."""\nx = 1\n') == [1]


def test_a_python_function_docstring_is_reported() -> None:
    assert python_comments('def f():\n    """What f does."""\n    return 1\n') == [2]


def test_a_python_class_docstring_is_reported() -> None:
    assert python_comments('class C:\n    """What C holds."""\n\n    x = 1\n') == [2]


def test_a_python_async_function_docstring_is_reported() -> None:
    assert python_comments('async def f():\n    """What f does."""\n    return 1\n') == [2]


def test_a_python_file_with_nothing_in_it_reports_nothing() -> None:
    assert python_comments("") == []


def test_a_python_statement_that_is_not_a_docstring_is_not_reported() -> None:
    assert python_comments("x = 1\n") == []


def test_a_python_number_standing_alone_is_not_read_as_a_docstring() -> None:
    assert python_comments("def f():\n    1\n") == []


def test_a_yaml_comment_is_reported() -> None:
    assert yaml_comments("---\njobs:\n  # why\n  a: 1\n") == [3]


def test_a_hash_inside_a_yaml_block_scalar_is_not_reported() -> None:
    assert yaml_comments('---\nrun: >-\n  echo "# not a comment"\n') == []


def test_a_hash_inside_a_quoted_yaml_string_is_not_reported() -> None:
    assert yaml_comments('---\nname: "a # b"\n') == []


def test_a_hash_comment_in_opentofu_is_reported() -> None:
    assert hcl_comments('# why\nresource "a" "b" {}\n') == [1]


def test_a_double_slash_comment_in_opentofu_is_reported() -> None:
    assert hcl_comments('resource "a" "b" {}\n// why\n') == [2]


def test_a_block_comment_in_opentofu_is_reported() -> None:
    assert hcl_comments("locals {\n  /* why\n     more why */\n}\n") == [2]


def test_a_hash_inside_an_opentofu_string_is_not_reported() -> None:
    assert hcl_comments('bucket = "a#b"\n') == []


def test_an_escaped_quote_does_not_end_an_opentofu_string() -> None:
    assert hcl_comments('bucket = "a\\"#b"\n') == []


def test_an_opentofu_string_nobody_closed_swallows_the_rest_of_the_file() -> None:
    assert hcl_comments('bucket = "a#b\n') == []


def test_an_opentofu_block_comment_nobody_closed_is_still_reported() -> None:
    assert hcl_comments("locals {\n  /* why\n") == [2]


def test_a_javascript_comment_is_reported() -> None:
    assert javascript_comments("const a = 1;\n// why\n") == [2]


def test_a_double_slash_inside_a_javascript_string_is_not_reported() -> None:
    assert javascript_comments('const a = "https://example.com";\n') == []


def test_a_double_slash_inside_a_javascript_template_literal_is_not_reported() -> None:
    assert javascript_comments("const a = `https://${host}`;\n") == []


def test_a_slash_inside_a_javascript_character_class_does_not_end_the_pattern() -> None:
    assert javascript_comments("const a = /[a-z/]+/;\n") == []


def test_a_javascript_pattern_after_return_is_not_read_as_division() -> None:
    assert javascript_comments("function f() {\n  return /a/;\n}\n") == []


def test_an_escaped_slash_does_not_end_a_javascript_pattern() -> None:
    assert javascript_comments("const a = /a\\/b/;\n") == []


def test_a_javascript_pattern_nobody_closed_swallows_the_rest_of_the_file() -> None:
    assert javascript_comments("const a = /abc") == []


def test_a_line_break_ends_a_javascript_pattern() -> None:
    assert javascript_comments("const a = /abc\n// why\n") == [2]


def test_a_comment_on_the_last_line_of_a_file_with_no_line_break_is_reported() -> None:
    assert javascript_comments("// why") == [1]


def test_a_javascript_division_is_not_read_as_a_pattern() -> None:
    assert javascript_comments("const a = b / c;\n// why\n") == [2]


def test_a_javascript_pattern_at_the_very_start_of_a_file_is_not_read_as_division() -> None:
    assert javascript_comments("/a/.test(b);\n") == []


def test_commented_files_names_the_file_and_the_line(tmp_path: Path) -> None:
    _write(_repo(tmp_path), SOURCE, "x = 1\n# why\n")
    assert commented_files(tmp_path) == [(SOURCE, 2)]


def test_commented_files_leaves_the_vendored_javascript_alone(tmp_path: Path) -> None:
    assert commented_files(_repo(tmp_path)) == []


def test_commented_files_does_not_read_a_markdown_file(tmp_path: Path) -> None:
    _write(_repo(tmp_path), PROSE, "# A heading, which is not a comment.\n")
    assert commented_files(tmp_path) == []


def test_main_answers_zero_when_nothing_carries_a_comment(tmp_path: Path) -> None:
    assert main(["--root", str(_repo(tmp_path))]) == 0


def test_main_answers_one_when_something_carries_a_comment(tmp_path: Path) -> None:
    _write(_repo(tmp_path), SOURCE, "# why\nx = 1\n")
    assert main(["--root", str(tmp_path)]) == 1


def test_main_prints_an_annotation_naming_the_file_and_the_line(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(_repo(tmp_path), SOURCE, "x = 1\n# why\n")
    main(["--root", str(tmp_path)])
    assert "::error file=src/counting.py,line=2::" in capsys.readouterr().out
