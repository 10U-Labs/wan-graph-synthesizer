from __future__ import annotations

import re

from repo_utils import REPO_ROOT

_ENDPOINTS = REPO_ROOT / "src" / "api" / "endpoints"

_LOADED = re.compile(r'load_handler\(\s*"([^"]+)"')
_BOUND = re.compile(r'"endpoint":\s*"([^"]+)"')


def _endpoints_driven() -> set[str]:
    names: set[str] = set()
    for path in (REPO_ROOT / "test").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        names.update(_LOADED.findall(text))
        names.update(_BOUND.findall(text))
    return names


def _endpoints_deployed() -> set[str]:
    return {
        str(handler.parent.parent.relative_to(_ENDPOINTS))
        for handler in _ENDPOINTS.glob("**/lambdas/handler.py")
    }


def test_every_endpoint_the_suite_drives_has_a_handler_where_the_loader_looks() -> None:
    assert sorted(_endpoints_driven() - _endpoints_deployed()) == []


def test_every_deployed_handler_is_one_some_test_drives() -> None:
    assert sorted(_endpoints_deployed() - _endpoints_driven()) == []
