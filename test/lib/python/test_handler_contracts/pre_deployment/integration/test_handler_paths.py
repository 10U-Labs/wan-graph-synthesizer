"""Contract: the handler files the loader computes paths to are where it expects them.

The loader turns an endpoint's name into one path -- ``src/api/endpoints/<name>/lambdas/
handler.py`` -- and every unit test of a deployed handler is loaded through it. That
layout is a presumption about ``src/`` written into ``lib/python/``, and the two are
changed by different people for different reasons: moving a handler is an endpoint's
business, and nothing in the endpoint's own tests would say that the shared loader had
stopped finding it.

Both directions are worth holding. A name the suite drives that resolves to no file fails
every one of that endpoint's unit tests at once, naming the endpoint rather than the move;
a handler that is deployed and that no test drives is a handler nothing has ever run.
"""

from __future__ import annotations

import re

from repo_utils import REPO_ROOT

_ENDPOINTS = REPO_ROOT / "src" / "api" / "endpoints"

# The two ways a test names an endpoint: to the loader outright, or in the configuration a
# contract subclass binds, which the contract then passes to the loader itself.
_LOADED = re.compile(r'load_handler\(\s*"([^"]+)"')
_BOUND = re.compile(r'"endpoint":\s*"([^"]+)"')


def _endpoints_driven() -> set[str]:
    """Every endpoint name the test suite hands to the loader, however it names it."""
    names: set[str] = set()
    for path in (REPO_ROOT / "test").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        names.update(_LOADED.findall(text))
        names.update(_BOUND.findall(text))
    return names


def _endpoints_deployed() -> set[str]:
    """Every endpoint keeping a handler where the loader looks for one."""
    return {
        str(handler.parent.parent.relative_to(_ENDPOINTS))
        for handler in _ENDPOINTS.glob("**/lambdas/handler.py")
    }


def test_every_endpoint_the_suite_drives_has_a_handler_where_the_loader_looks() -> None:
    """A moved handler fails here, once and by name, instead of inside each of its tests."""
    assert sorted(_endpoints_driven() - _endpoints_deployed()) == []


def test_every_deployed_handler_is_one_some_test_drives() -> None:
    """A handler no test names is code that ships without a unit tier having run it."""
    assert sorted(_endpoints_deployed() - _endpoints_driven()) == []
