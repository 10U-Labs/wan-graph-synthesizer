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
from typing import Any, cast

import pytest
import yaml

import seed
from repo_utils import REPO_ROOT
from seed import _carrier_cities, _city_key, _rows, _slug
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


def _written_by_tenant(recorder: UrlopenRecorder, resource: str) -> dict[str, Any]:
    """Each tenant's *resource* document as seed sent it, keyed by tenant id."""
    return {
        request.full_url.split("/")[-2]: json.loads(cast("bytes", request.data))
        for request in recorder.requests
        if request.full_url.endswith(f"/{resource}")
    }


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


def _declared_coverage_targets() -> dict[str, float]:
    """Each tenant's coverage target, read from the backbone block of its own config."""
    return {
        _slug(path.stem): yaml.safe_load(
            path.read_text(encoding="utf-8"))["backbone"]["coverage_target_miles"]
        for path in seed.ETC.glob("*.yml")
    }


def test_pipeline_writes_each_tenant_the_coverage_target_its_config_declares(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each knobs document carries the target its config declares, under the stored key.

    The document is now assembled rather than passed through: the config names the
    target ``backbone.coverage_target_miles`` and the synthesizer reads it as
    ``backbone_coverage_target_miles``, so the two spellings must agree tenant by
    tenant, which neither file can establish alone.
    """
    _seed(urlopen_recorder, monkeypatch)
    assert _written_by_tenant(urlopen_recorder, "knobs") == {
        tenant: {"backbone_coverage_target_miles": target}
        for tenant, target in _declared_coverage_targets().items()
    }


def test_pipeline_writes_every_tenant_the_regions_of_the_file_its_config_names(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every tenant is seeded regions from the bare path its ``inputs.providers`` names.

    The config names the file and only the file holds the rows, so neither side says
    alone that a tenant ends up with any regions at all. A shape the reader mishandles
    is the failure this catches: it delivers an empty document rather than an error, and
    a tenant seeded no regions has no cloud demand to home.
    """
    _seed(urlopen_recorder, monkeypatch)
    written = _written_by_tenant(urlopen_recorder, "provider-regions")
    seeded = sum(1 for regions in written.values() if regions)
    assert seeded == len(list(seed.ETC.glob("*.yml")))


def _declared_off_net_paths() -> set[str]:
    """Every seat file the roster's configs name under ``inputs.forced``."""
    paths: set[str] = set()
    for config in seed.ETC.glob("*.yml"):
        declared = yaml.safe_load(config.read_text(encoding="utf-8"))
        forced = declared.get("inputs", {}).get("forced")
        if forced:
            paths.add(forced)
    return paths


def test_no_declared_off_net_seat_is_a_city_a_carrier_already_serves() -> None:
    """No off-net file the roster names lists a city the carrier points files cover.

    Neither side can establish this alone: an off-net seat exists to offer a city no
    carrier reaches, and only the carrier points say which cities those are. An overlap
    would leave the file promising a seat the synthesizer never builds, since it seats
    the operator's pin on the real point instead.
    """
    carriers = _carrier_cities()
    overlapping = sorted(
        city
        for path in _declared_off_net_paths()
        for city in {_city_key(row) for row in _rows(REPO_ROOT / path)} & carriers
    )
    assert overlapping == []


def _tenants_written(paths: list[str], resource: str) -> int:
    """How many tenants seed wrote *resource* for, over the paths it requested."""
    return sum(1 for path in paths if re.fullmatch(rf"tenants/[^/]+/{resource}", path))


def test_pipeline_writes_a_label_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a label resource for every tenant config file."""
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, "label") == len(list(seed.ETC.glob("*.yml")))


def test_pipeline_writes_a_forced_homes_document_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a forced-homes resource for every tenant config file.

    The list is empty in every config, which is exactly the state that would hide a
    tenant seeded without the document at all -- and the synthesizer reads its config
    resources unconditionally, so a tenant missing one gets no WAN rather than a default.
    """
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, "forced-homes") == len(list(seed.ETC.glob("*.yml")))
