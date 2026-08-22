from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from test_fixtures.aws import get_log_group_info

_GROUP = "/aws/lambda/wan-synthesizer-carriers"


def _logs(*groups: dict[str, Any]) -> Any:
    return SimpleNamespace(describe_log_groups=lambda **_kwargs: {"logGroups": list(groups)})


def test_a_group_cloudwatch_answers_for_reads_present() -> None:
    assert get_log_group_info(_logs({"logGroupName": _GROUP}), _GROUP)["exists"] is True


def test_a_prefix_query_answering_nothing_reads_absent() -> None:
    assert get_log_group_info(_logs(), _GROUP)["exists"] is False


def test_a_longer_name_sharing_the_prefix_is_not_the_group_asked_for() -> None:
    neighbour = {"logGroupName": f"{_GROUP}-merge"}
    assert get_log_group_info(_logs(neighbour), _GROUP)["exists"] is False


def test_the_retention_reported_is_the_one_the_group_carries() -> None:
    group = {"logGroupName": _GROUP, "retentionInDays": 14}
    assert get_log_group_info(_logs(group), _GROUP)["retention"] == 14


def test_a_group_keeping_records_forever_reports_no_retention() -> None:
    assert get_log_group_info(_logs({"logGroupName": _GROUP}), _GROUP)["retention"] is None


def test_an_absent_group_reports_no_retention() -> None:
    assert get_log_group_info(_logs(), _GROUP)["retention"] is None


def test_the_group_named_in_the_answer_is_the_one_asked_about() -> None:
    assert get_log_group_info(_logs(), _GROUP)["name"] == _GROUP
