"""Unit tests for the read of a Lambda's log group and how long it keeps what it holds.

Every endpoint's post-deployment tier asserts that its function has a log group and that
the group discards records on the schedule the declaration asks for. Both answers come
from here, and the retention half is the one nobody would notice going wrong: a group
reported as keeping records forever costs money quietly, and one reported as keeping them
for a fortnight when it keeps them for a day loses the record of an incident.

CloudWatch is asked by prefix, which is what makes the lookup worth covering: a prefix
matches every longer name too, so a group that merely starts with the name asked for is
not the group asked for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from test_fixtures.aws import get_log_group_info

_GROUP = "/aws/lambda/wan-synthesizer-carriers"


def _logs(*groups: dict[str, Any]) -> Any:
    """A CloudWatch Logs client answering a prefix query with ``groups``."""
    return SimpleNamespace(describe_log_groups=lambda **_kwargs: {"logGroups": list(groups)})


def test_a_group_cloudwatch_answers_for_reads_present() -> None:
    """The group the deployment declared is there, which is the ordinary case."""
    assert get_log_group_info(_logs({"logGroupName": _GROUP}), _GROUP)["exists"] is True


def test_a_prefix_query_answering_nothing_reads_absent() -> None:
    """No group under that prefix is an absent group, and the tier says so."""
    assert get_log_group_info(_logs(), _GROUP)["exists"] is False


def test_a_longer_name_sharing_the_prefix_is_not_the_group_asked_for() -> None:
    """CloudWatch answers by prefix; the name is compared in full so a neighbour cannot pass."""
    neighbour = {"logGroupName": f"{_GROUP}-merge"}
    assert get_log_group_info(_logs(neighbour), _GROUP)["exists"] is False


def test_the_retention_reported_is_the_one_the_group_carries() -> None:
    """The declaration asks for a number of days, and this is what it is checked against."""
    group = {"logGroupName": _GROUP, "retentionInDays": 14}
    assert get_log_group_info(_logs(group), _GROUP)["retention"] == 14


def test_a_group_keeping_records_forever_reports_no_retention() -> None:
    """CloudWatch leaves the field out when nothing expires, and that is a finding, not a gap."""
    assert get_log_group_info(_logs({"logGroupName": _GROUP}), _GROUP)["retention"] is None


def test_an_absent_group_reports_no_retention() -> None:
    """There is no schedule to report for a group that is not there."""
    assert get_log_group_info(_logs(), _GROUP)["retention"] is None


def test_the_group_named_in_the_answer_is_the_one_asked_about() -> None:
    """A failure has to name the group, and the name it carries is the one that was asked for."""
    assert get_log_group_info(_logs(), _GROUP)["name"] == _GROUP
