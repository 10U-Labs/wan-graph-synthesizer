from __future__ import annotations

from test_terraform_config import (
    COMMON_OUTPUTS_FILE,
    STATE_BUCKET,
    TEST_AWS_REGION,
    common_outputs,
    lambda_handler_names,
)

_NAMES_READ = ("aws_region", "state_bucket", "lambda_handler_names")


def test_the_common_module_the_reads_point_at_is_there() -> None:
    assert COMMON_OUTPUTS_FILE.is_file() is True


def test_every_output_the_module_reads_by_name_is_declared() -> None:
    declared = common_outputs()
    assert [name for name in _NAMES_READ if name not in declared] == []


def test_the_region_every_client_is_built_for_is_the_declared_one() -> None:
    assert TEST_AWS_REGION == common_outputs()["aws_region"]


def test_the_state_bucket_the_suite_inspects_is_the_declared_one() -> None:
    assert STATE_BUCKET == common_outputs()["state_bucket"]


def test_every_declared_handler_name_survives_being_offered() -> None:
    assert lambda_handler_names() == common_outputs()["lambda_handler_names"]
