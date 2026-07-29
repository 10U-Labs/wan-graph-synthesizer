"""Integration tests: seed's pipeline over the real inputs, with the API mocked.

These run the real CLI pipeline (``seed.main``) over the repository's own
``data/`` and ``etc/`` inputs with the HTTP boundary replaced in-process, then
assert the cross-file contract that every resource seed touches is declared in
the OpenAPI spec the API is built from. The roster in ``etc/`` is also checked
against the seed workflow's explicit yamllint file list, which names each config
one by one and so goes stale whenever a tenant is added or dropped.
"""

from __future__ import annotations

import json
import re
import sys

import pytest

import seed
from repo_utils import REPO_ROOT
from test_http_doubles import UrlopenRecorder

_API = "http://stub"


def _declared_templates() -> set[str]:
    """The path templates declared in the OpenAPI spec, minus the prefix.

    Seed stores inputs (PUT), triggers builds (POST ``carriers/merge`` and
    ``tenants/{t}/wan``), reads the tenant listing (GET) and removes tenants git has
    dropped (DELETE), so every declared path is one seed may legitimately request.
    """
    spec = json.loads(
        (REPO_ROOT / "src/www/api/openapi.json").read_text(encoding="utf-8"))
    prefix = "/wan-graph-synthesizer/"
    return {path[len(prefix):] for path in spec["paths"] if path.startswith(prefix)}


def _linted_configs() -> set[str]:
    """The ``etc/`` configs the seed workflow's yamllint step names, minus the prefix.

    The step lists every file explicitly rather than globbing, so these are the only
    ``etc/<name>.yml`` tokens in the workflow.
    """
    workflow = (REPO_ROOT / ".github/workflows/seed.yml").read_text(encoding="utf-8")
    return set(re.findall(r"etc/(\w+\.yml)", workflow))


def _matches(path: str, template: str) -> bool:
    """True if a concrete *path* matches an OpenAPI *template* with placeholders."""
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.fullmatch(pattern, path) is not None


def _seed(recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run seed.main over the real inputs and return the written resource paths."""
    monkeypatch.setattr(sys, "argv", ["seed", _API])
    seed.main()
    return recorder.paths(_API)


def test_every_requested_path_is_declared_in_openapi(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every path seed requests (input, build, listing or removal) is declared in the spec."""
    templates = _declared_templates()
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


def test_yamllint_names_every_tenant_config() -> None:
    """The workflow's yamllint file list names exactly the configs the roster declares."""
    declared = {path.name for path in seed.ETC.glob("*.yml")}
    assert _linted_configs() == declared


def test_pipeline_writes_a_label_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a label resource for every tenant config file."""
    paths = _seed(urlopen_recorder, monkeypatch)
    tenants = len(list(seed.ETC.glob("*.yml")))
    labels = sum(1 for path in paths if re.fullmatch(r"tenants/[^/]+/label", path))
    assert labels == tenants
