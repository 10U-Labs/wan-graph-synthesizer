from __future__ import annotations

import urllib.request

import pytest

import seed
from test_http_doubles import CallRecorder, UrlopenRecorder


@pytest.fixture
def urlopen_recorder(monkeypatch: pytest.MonkeyPatch) -> UrlopenRecorder:
    recorder = UrlopenRecorder()
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


@pytest.fixture
def instant_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "RETRY_PAUSE_SECONDS", 0)


@pytest.fixture
def put_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_put", recorder)
    return recorder


@pytest.fixture
def post_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_post", recorder)
    return recorder


@pytest.fixture
def delete_recorder(monkeypatch: pytest.MonkeyPatch) -> CallRecorder:
    recorder = CallRecorder()
    monkeypatch.setattr(seed, "_delete", recorder)
    return recorder
