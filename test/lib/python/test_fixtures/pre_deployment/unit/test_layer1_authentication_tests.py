from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from test_fixtures.integration import create_simple_layer1_authentication_tests


def _sts(**identity: Any) -> Any:
    return SimpleNamespace(get_caller_identity=lambda: identity)


def _layer() -> Any:
    return create_simple_layer1_authentication_tests()()


def test_credentials_resolving_to_an_account_pass() -> None:
    assert _layer().test_aws_credentials_valid(_sts(Account="781581267945")) is None


def test_credentials_resolving_to_no_account_fail() -> None:
    with pytest.raises(AssertionError):
        _layer().test_aws_credentials_valid(_sts(Account=None))


def test_an_identity_carrying_an_arn_passes() -> None:
    identity = _sts(Arn="arn:aws:sts::781581267945:assumed-role/deploy")
    assert _layer().test_aws_credentials_not_expired(identity) is None


def test_an_identity_carrying_no_arn_fails() -> None:
    with pytest.raises(AssertionError):
        _layer().test_aws_credentials_not_expired(_sts(Account="781581267945"))
