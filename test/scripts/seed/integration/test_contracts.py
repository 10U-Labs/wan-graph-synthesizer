"""Integration tests: seed's pipeline over the real inputs, with the API mocked.

These run the real CLI pipeline (``seed.main``) over the repository's own
``data/`` and ``etc/`` inputs with the HTTP boundary replaced in-process, then
assert the cross-file contract that every resource seed touches is declared in
the OpenAPI spec the API is built from. The roster in ``etc/`` is also checked
against the seed workflow's explicit yamllint file list, which names each config
one by one and so goes stale whenever a tenant is added or dropped.

One contract here reads no request at all. A tenant's backbone knobs and the
carrier files are two inputs that have to agree about what the fiber can do, and
this is the only tier that holds both, so it is where that agreement is asserted.
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
from synthesizer.ceiling import independent_route_ceiling
from synthesizer.codec import load_substrate
from synthesizer.graphs import build_adjacency
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


def _backbone_blocks() -> dict[str, dict[str, Any]]:
    """Each tenant's whole ``backbone`` block, keyed by the tenant id seed derives.

    Every backbone knob a contract here asserts on is read through this one place, so a
    test names the key it means and nothing re-opens the config files to find it.
    """
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))["backbone"]
        for path in seed.ETC.glob("*.yml")
    }


def _declared_coverage_targets() -> dict[str, int]:
    """Each tenant's coverage target, read from the backbone block of its own config."""
    return {
        tenant: backbone["coverage_target_miles"]
        for tenant, backbone in _backbone_blocks().items()
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


def _substrate() -> tuple[dict[str, str], dict[str, list[tuple[str, float]]]]:
    """The merged carrier substrate: its cities by display name, and its fiber adjacency.

    Every carrier's points and every carrier's spans, read with seed's own reader and
    merged by the same loader the API uses, so the graph measured here is the graph the
    synthesizer starts from. The files are taken in sorted order because a generated id
    depends on what claimed the name first, and the mapping back from a config's
    ``City, ST`` spelling to that id is what the caller needs.
    """
    points = [
        row
        for path in sorted((seed.DATA / "vertices" / "carriers").glob("*.csv"))
        for row in _rows(path)
    ]
    spans = [
        row for path in sorted((seed.DATA / "edges").glob("*.csv")) for row in _rows(path)
    ]
    vertices, edges = load_substrate(points, spans)
    return {vertex.name: vertex.id for vertex in vertices}, build_adjacency(edges)


def _pinned_ids(backbone: dict[str, Any], by_name: dict[str, str]) -> tuple[str, ...]:
    """The tenant's pinned backbone cities as substrate ids, skipping any it has no point for.

    A pin the carrier files do not serve is seated by fabricating a point for it, which this
    graph does not have. Leaving it out costs the count a place a route could have ended,
    which can only make the bound below smaller.
    """
    names = (backbone.get("forced") or {}).get("nodes") or []
    return tuple(by_name[name] for name in names if name in by_name)


def _exemption_ceiling_bounds() -> list[tuple[str, str, int, int]]:
    """Every exempt city's ceiling lower bound beside the degree its tenant asks for.

    The bound counts routes from the city to the tenant's pinned backbone cities that share
    no city on the way, over the merged carrier substrate. It is a floor rather than the
    real ceiling for two reasons, and both point the same way: the real run seats backbone
    nodes beyond the pins, which gives routes more distinct places to end, and it fabricates
    on-net points and seats off-net ones, which adds spans. Neither can lower a maximum
    flow, so the real ceiling is at least what this returns.

    An exempt city the carrier files hold no point for is left out, since there is no graph
    to measure it on and a silent zero would read as a proven limit.
    """
    by_name, adjacency = _substrate()
    bounds: list[tuple[str, str, int, int]] = []
    for tenant, backbone in sorted(_backbone_blocks().items()):
        pinned = _pinned_ids(backbone, by_name)
        for city in backbone.get("degree_exempt") or []:
            if city in by_name:
                bound = independent_route_ceiling(by_name[city], pinned, adjacency)
                bounds.append((tenant, city, bound, backbone["number_of_diverse_paths"]))
    return bounds


def test_no_tenant_exempts_a_city_its_own_fiber_already_accounts_for() -> None:
    """No exempt city is one whose ceiling would have lowered its target anyway.

    Neither file settles this alone: the config says which cities are excused the degree,
    and only the carrier files say which of them could have met it. A city that cannot is
    held to what its fiber carries and passes on that, so excusing it changes no outcome
    and costs the report the line that would have explained the design. A city that can is
    a different matter, and the exemption is then the only reason a real shortfall goes
    unmentioned -- so an exemption is worth keeping only where the fiber does not already
    account for the gap.

    Boston was a city of the first kind: every route out of it passes through Albany or
    Stamford, so it could never hold three independent links, and it came off the list once
    the ceiling said so. San Jose is a city of the second kind, with three routes to three
    different pinned cities that share no city between them.
    """
    assert [
        (tenant, city, bound, degree)
        for tenant, city, bound, degree in _exemption_ceiling_bounds()
        if bound < degree
    ] == []
