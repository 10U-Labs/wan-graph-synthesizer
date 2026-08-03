"""Unit tests for locating one resource block inside a parsed OpenTofu document.

A test that asserts on a declared setting -- a bucket's name, a function's memory -- finds
the block through this. It answers ``None`` for a block that is not there, and ``None`` is
also what a caller gets when the document is shaped differently than expected, so the two
have to be told apart deliberately: a test reading a setting off ``None`` fails naming the
setting, and the reason is that the block was never found.

The documents here are literals rather than files. What is under test is the walk, and a
walk is exercised by the shapes it has to survive, several of which no parser emits.
"""

from __future__ import annotations

from test_terraform_config import find_resource

_DECLARED: dict[str, object] = {
    "resource": [
        {"aws_s3_bucket": {"store": {"bucket": "the-store", "force_destroy": False}}},
        {"aws_lambda_function": {"synthesizer": {"memory_size": 2048}}},
    ]
}


def test_the_body_returned_is_the_one_declared_under_that_name() -> None:
    """A found block hands back its whole body, which is what the caller reads settings off."""
    assert find_resource(_DECLARED, "aws_s3_bucket", "store") == {
        "bucket": "the-store",
        "force_destroy": False,
    }


def test_a_block_declared_later_in_the_document_is_found_too() -> None:
    """The walk covers every block, not the first one, so declaration order decides nothing."""
    assert find_resource(_DECLARED, "aws_lambda_function", "synthesizer") == {"memory_size": 2048}


def test_a_name_that_is_not_declared_is_reported_absent() -> None:
    """A resource of the right type under another name is not the resource asked for."""
    assert find_resource(_DECLARED, "aws_s3_bucket", "logs") is None


def test_a_type_that_is_not_declared_is_reported_absent() -> None:
    """A type the document never mentions is absent rather than an error."""
    assert find_resource(_DECLARED, "aws_dynamodb_table", "store") is None


def test_a_document_declaring_no_resources_is_reported_absent() -> None:
    """An outputs-only file is the ordinary case for the shared common module."""
    assert find_resource({"output": []}, "aws_s3_bucket", "store") is None


def test_a_document_whose_resources_are_not_a_list_is_reported_absent() -> None:
    """Nothing is walked when the document is shaped unlike anything the parser emits."""
    assert find_resource({"resource": "not a list"}, "aws_s3_bucket", "store") is None


def test_an_entry_that_is_not_a_block_is_stepped_over() -> None:
    """One unreadable entry does not hide the blocks declared after it."""
    document: dict[str, object] = {
        "resource": ["not a block", {"aws_s3_bucket": {"store": {"bucket": "b"}}}]
    }
    assert find_resource(document, "aws_s3_bucket", "store") == {"bucket": "b"}


def test_a_type_holding_something_other_than_named_blocks_is_stepped_over() -> None:
    """A type whose entry is not a mapping of names holds no name, so the walk continues."""
    document: dict[str, object] = {"resource": [{"aws_s3_bucket": "not named blocks"}]}
    assert find_resource(document, "aws_s3_bucket", "store") is None


def test_a_body_that_is_not_a_block_body_is_reported_absent() -> None:
    """A name found carrying something other than a body is no more use than a name absent."""
    document: dict[str, object] = {"resource": [{"aws_s3_bucket": {"store": "not a body"}}]}
    assert find_resource(document, "aws_s3_bucket", "store") is None
