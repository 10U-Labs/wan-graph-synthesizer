from __future__ import annotations

from collections.abc import Iterator

import pytest

from test_http_doubles import StubApi


@pytest.fixture
def stub_api() -> Iterator[StubApi]:
    with StubApi() as api:
        yield api
