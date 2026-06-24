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
