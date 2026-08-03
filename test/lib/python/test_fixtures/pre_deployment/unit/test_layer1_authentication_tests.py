"""Unit tests for the authentication layer every deployable unit takes rather than writes.

The authentication layer asks one question -- are these credentials valid -- and every
unit asks it the same way, so the tests are built once and taken by each. That makes it the
single answer eleven pre-deployment tiers rest on: if it passes on credentials that do not
resolve, every unit's chain starts from a presumption that is false, and each of them
fails later at a layer that is not the one at fault.

What is exercised here is the class the factory returns, driven with a stand-in for STS.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from test_fixtures.integration import create_simple_layer1_authentication_tests


def _sts(**identity: Any) -> Any:
    """An STS client answering ``get_caller_identity`` with the identity given."""
    return SimpleNamespace(get_caller_identity=lambda: identity)


def _layer() -> Any:
    """The authentication tests as a unit under test rather than as tests to be collected."""
    return create_simple_layer1_authentication_tests()()


def test_credentials_resolving_to_an_account_pass() -> None:
    """An account in the answer is what valid credentials look like."""
    assert _layer().test_aws_credentials_valid(_sts(Account="781581267945")) is None


def test_credentials_resolving_to_no_account_fail() -> None:
    """An answer carrying no account is not an identity, however well formed it is."""
    with pytest.raises(AssertionError):
        _layer().test_aws_credentials_valid(_sts(Account=None))


def test_an_identity_carrying_an_arn_passes() -> None:
    """A live session names the principal it belongs to."""
    identity = _sts(Arn="arn:aws:sts::781581267945:assumed-role/deploy")
    assert _layer().test_aws_credentials_not_expired(identity) is None


def test_an_identity_carrying_no_arn_fails() -> None:
    """An answer without a principal is the shape an expired session comes back in."""
    with pytest.raises(AssertionError):
        _layer().test_aws_credentials_not_expired(_sts(Account="781581267945"))
