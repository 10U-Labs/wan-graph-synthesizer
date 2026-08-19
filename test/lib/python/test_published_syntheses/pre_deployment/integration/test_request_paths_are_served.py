"""Contract: the reader asks the service only for resources the API says it serves.

``src/www/api/openapi.json`` is the list of what a reader outside the service is allowed
to ask it for, and nothing held this tier's reader against it. That is how the reader came
to take a tenant's published network out of the S3 bucket the synthesizer writes to
instead: the bucket answers any key at all, so nothing said the front door existed, and
what the bucket holds is two of the eight settings a ``backbone`` block declares rather
than the whole answer (GitHub issue #47).

This holds one file in the repository against another and needs no deployment to do it. A
path the reader asks for that the API does not define comes back as an HTTP 403 an hour
into a live post-deployment run, if the run reaches it at all; here it is a failure on the
push that wrote it.

The tenant id the paths are built with is the literal ``{tenant}``, which is the name the
spec gives that segment. Substituting it makes each built path the spec's own key, so what
is compared is the whole path the reader would send and not a prefix of it.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from repo_utils import REPO_ROOT
from seed import DEFAULT_API
from test_published_syntheses import request_paths

_SPEC = json.loads(
    (REPO_ROOT / "src" / "www" / "api" / "openapi.json").read_text(encoding="utf-8"))
# The stage prefix every path sits under, taken from the base URL the reader sends to, so
# a service remounted somewhere else is a failure here rather than a wrong request later.
_BASE = urlsplit(DEFAULT_API).path


def _unserved(path: str) -> bool:
    """True when the spec defines no GET for the resource *path* names."""
    return "get" not in _SPEC["paths"].get(f"{_BASE}/{path}", {})


def test_the_reader_asks_the_service_for_something() -> None:
    """Without a path to check, the contract below passes on a reader that reads nothing."""
    assert request_paths("{tenant}") != []


def test_every_path_the_reader_asks_for_is_one_the_api_serves() -> None:
    """Every request the reader would send names a resource the spec defines a GET for."""
    assert [path for path in request_paths("{tenant}") if _unserved(path)] == []
