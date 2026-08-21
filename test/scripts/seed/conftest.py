"""Fixtures shared by the seed CLI test tiers."""

from __future__ import annotations

import urllib.request

import pytest

import seed
from test_http_doubles import CallRecorder, UrlopenRecorder


@pytest.fixture
def urlopen_recorder(monkeypatch: pytest.MonkeyPatch) -> UrlopenRecorder:
    """Replace urllib.request.urlopen with an in-process recorder."""
    recorder = UrlopenRecorder()
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


@pytest.fixture
def instant_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the pause _send waits out before a retry down to nothing.

    The seed waits a second before trying a dropped connection again, which is a
    reasonable pause on a real network and a second of a unit tier's runtime spent
    asleep for every test that reaches it.
    """
    monkeypatch.setattr(seed, "RETRY_PAUSE_SECONDS", 0)


@pytest.fixture
def put_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    """Replace seed._put with a recorder of its (api, path, body) calls."""
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_put", recorder)
    return recorder


@pytest.fixture
def post_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    """Replace seed._post with a recorder of its (api, path) calls."""
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_post", recorder)
    return recorder


@pytest.fixture
def delete_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    """Replace seed._delete with a recorder of its (api, path) calls."""
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_delete", recorder)
    return recorder
