"""Integration tests: seed's pipeline over the real inputs, with the API mocked.

These run the real CLI pipeline (``seed.main``) over the repository's own
``data/`` and ``etc/`` inputs with the HTTP boundary replaced in-process, then
assert the cross-file contract that every resource seed writes is a declared
PUT in the OpenAPI spec the API is built from.
"""

from __future__ import annotations

import json
import re

import pytest

import seed
from http_test_doubles import UrlopenRecorder
from repo_utils import REPO_ROOT

_API = "http://stub"


def _put_templates() -> set[str]:
    """The PUT path templates declared in the OpenAPI spec, minus the prefix."""
    spec = json.loads(
        (REPO_ROOT / "src/www/api/openapi.json").read_text(encoding="utf-8"))
    prefix = "/wan-graph-synthesizer/"
    return {
        path[len(prefix):]
        for path, operations in spec["paths"].items()
        if "put" in operations and path.startswith(prefix)
    }


def _matches(path: str, template: str) -> bool:
    """True if a concrete *path* matches an OpenAPI *template* with placeholders."""
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.fullmatch(pattern, path) is not None


def _seed(recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run seed.main over the real inputs and return the written resource paths."""
    monkeypatch.setattr(seed.sys, "argv", ["seed", _API])
    seed.main()
    return recorder.paths(_API)


def test_every_written_path_is_declared_in_openapi(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every resource seed writes is a declared PUT in the OpenAPI spec."""
    templates = _put_templates()
    undeclared = [
        path for path in _seed(urlopen_recorder, monkeypatch)
        if not any(_matches(path, template) for template in templates)
    ]
    assert undeclared == []


def test_pipeline_writes_at_least_one_carrier(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding the real inputs writes at least one carrier's vertices."""
    paths = _seed(urlopen_recorder, monkeypatch)
    assert any(re.fullmatch(r"carriers/[^/]+/vertices", path) for path in paths)


def test_pipeline_writes_a_label_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a label resource for every tenant config file."""
    paths = _seed(urlopen_recorder, monkeypatch)
    tenants = len(list(seed.ETC.glob("*.yml")))
    labels = sum(1 for path in paths if re.fullmatch(r"tenants/[^/]+/label", path))
    assert labels == tenants
