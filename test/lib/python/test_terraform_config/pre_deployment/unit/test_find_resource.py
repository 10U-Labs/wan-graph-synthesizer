from __future__ import annotations

from test_terraform_config import find_resource

_DECLARED: dict[str, object] = {
    "resource": [
        {"aws_s3_bucket": {"store": {"bucket": "the-store", "force_destroy": False}}},
        {"aws_lambda_function": {"synthesizer": {"memory_size": 2048}}},
    ]
}


def test_the_body_returned_is_the_one_declared_under_that_name() -> None:
    assert find_resource(_DECLARED, "aws_s3_bucket", "store") == {
        "bucket": "the-store",
        "force_destroy": False,
    }


def test_a_block_declared_later_in_the_document_is_found_too() -> None:
    assert find_resource(_DECLARED, "aws_lambda_function", "synthesizer") == {"memory_size": 2048}


def test_a_name_that_is_not_declared_is_reported_absent() -> None:
    assert find_resource(_DECLARED, "aws_s3_bucket", "logs") is None


def test_a_type_that_is_not_declared_is_reported_absent() -> None:
    assert find_resource(_DECLARED, "aws_dynamodb_table", "store") is None


def test_a_document_declaring_no_resources_is_reported_absent() -> None:
    assert find_resource({"output": []}, "aws_s3_bucket", "store") is None


def test_a_document_whose_resources_are_not_a_list_is_reported_absent() -> None:
    assert find_resource({"resource": "not a list"}, "aws_s3_bucket", "store") is None


def test_an_entry_that_is_not_a_block_is_stepped_over() -> None:
    document: dict[str, object] = {
        "resource": ["not a block", {"aws_s3_bucket": {"store": {"bucket": "b"}}}]
    }
    assert find_resource(document, "aws_s3_bucket", "store") == {"bucket": "b"}


def test_a_type_holding_something_other_than_named_blocks_is_stepped_over() -> None:
    document: dict[str, object] = {"resource": [{"aws_s3_bucket": "not named blocks"}]}
    assert find_resource(document, "aws_s3_bucket", "store") is None


def test_a_body_that_is_not_a_block_body_is_reported_absent() -> None:
    document: dict[str, object] = {"resource": [{"aws_s3_bucket": {"store": "not a body"}}]}
    assert find_resource(document, "aws_s3_bucket", "store") is None
