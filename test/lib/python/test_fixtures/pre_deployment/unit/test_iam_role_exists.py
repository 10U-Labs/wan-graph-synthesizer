"""Unit tests for the probe that asks IAM whether a role is there.

A deployed Lambda runs as a role, and the post-deployment tier asks this whether that role
exists before saying anything about what it may reach. The answer is a bare ``True`` or
``False``, so a wrong one is indistinguishable from the truth at the point it is read: the
tier reports the deployment's role missing and names the deployment.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from test_fixtures.aws import iam_role_exists


class _NoSuchEntity(Exception):
    """Stand-in for the IAM client's NoSuchEntityException."""


def _iam(*known: str) -> Any:
    """An IAM client holding the roles named and nothing else."""

    def get_role(**kwargs: Any) -> dict[str, Any]:
        """Answer for a role, or refuse the way IAM refuses one it does not hold."""
        if kwargs["RoleName"] not in known:
            raise _NoSuchEntity()
        return {"Role": {"RoleName": kwargs["RoleName"]}}

    return SimpleNamespace(
        get_role=get_role,
        exceptions=SimpleNamespace(NoSuchEntityException=_NoSuchEntity),
    )


_ROLE = "wan-synthesizer-wan-lambda"


def test_a_role_iam_answers_for_reads_present() -> None:
    """The role the deployment declared is there, which is the ordinary case."""
    assert iam_role_exists(_iam(_ROLE), _ROLE) is True


def test_a_role_iam_does_not_hold_reads_absent() -> None:
    """A refusal naming no such entity is an absent role and not a failed probe."""
    assert iam_role_exists(_iam(), _ROLE) is False


def test_a_role_under_another_name_is_not_the_role_asked_for() -> None:
    """The name is the whole of the question, so a near miss is a miss."""
    assert iam_role_exists(_iam(_ROLE), "wan-synthesizer") is False
