from __future__ import annotations

import json
from urllib.parse import urlsplit

from repo_utils import REPO_ROOT
from seed import DEFAULT_API
from test_published_syntheses import request_paths

_SPEC = json.loads(
    (REPO_ROOT / "src" / "www" / "api" / "openapi.json").read_text(encoding="utf-8"))
_BASE = urlsplit(DEFAULT_API).path


def _unserved(path: str) -> bool:
    return "get" not in _SPEC["paths"].get(f"{_BASE}/{path}", {})


def test_the_reader_asks_the_service_for_something() -> None:
    assert request_paths("{tenant}") != []


def test_every_path_the_reader_asks_for_is_one_the_api_serves() -> None:
    assert [path for path in request_paths("{tenant}") if _unserved(path)] == []
