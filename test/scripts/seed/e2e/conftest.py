"""Fixtures for seed end-to-end tests (a localhost stub API, no live resources)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from http_test_doubles import StubApi


@pytest.fixture
def stub_api() -> Iterator[StubApi]:
    """Run a localhost stub API recording PUTs for the duration of a test."""
    with StubApi() as api:
        yield api
