from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from collections.abc import Callable
from typing import Any, cast

import pytest
import yaml

import seed
from repo_utils import REPO_ROOT
from seed import _carrier_cities, _carrier_names, _city_key, _mapping_rows, _rows, _slug
from synthesizer.ceiling import PathProofInputs, independent_path_ceiling
from synthesizer.codec import load_merged_carriers, load_regions, load_sites
from synthesizer.graphs import build_adjacency
from synthesizer.input_graph import FiberSegment, Site, haversine_miles
from test_http_doubles import UrlopenRecorder

_API = "http://stub"


def _declared_templates() -> set[str]:
    spec = json.loads(
        (REPO_ROOT / "src/www/api/openapi.json").read_text(encoding="utf-8"))
    prefix = f"{urlsplit(seed.DEFAULT_API).path}/"
    return {path[len(prefix):] for path in spec["paths"] if path.startswith(prefix)}


def _linted_configs() -> set[str]:
    workflow = (REPO_ROOT / ".github/workflows/seed.yml").read_text(encoding="utf-8")
    return set(re.findall(r"etc/(\w+\.yml)", workflow))


def _matches(path: str, template: str) -> bool:
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.fullmatch(pattern, path) is not None


def _seed(recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(sys, "argv", ["seed", _API])
    seed.main()
    return recorder.paths(_API)


def _written_by_tenant(recorder: UrlopenRecorder, resource: str) -> dict[str, Any]:
    return {
        request.full_url.split("/")[-2]: json.loads(cast("bytes", request.data))
        for request in recorder.requests
        if request.full_url.endswith(f"/{resource}")
    }


def test_every_requested_path_is_declared_in_openapi(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    templates = _declared_templates()
    undeclared = [
        path for path in _seed(urlopen_recorder, monkeypatch)
        if not any(_matches(path, template) for template in templates)
    ]
    assert undeclared == []


def test_pipeline_writes_at_least_one_carrier(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _seed(urlopen_recorder, monkeypatch)
    assert any(re.fullmatch(r"carriers/[^/]+/pops", path) for path in paths)


def _backbone_keys_seed_reads() -> set[str]:
    source = (REPO_ROOT / "scripts" / "seed.py").read_text(encoding="utf-8")
    return set(re.findall(r'backbone(?:\[|\.get\()"([^"]+)"', source))


def test_no_tenant_declares_a_backbone_key_the_seed_does_not_read() -> None:
    declared: set[str] = set()
    for config in sorted((REPO_ROOT / "etc").glob("*.yml")):
        declared |= set(yaml.safe_load(config.read_text(encoding="utf-8"))["backbone"])
    assert declared <= _backbone_keys_seed_reads()


def test_yamllint_names_every_tenant_config() -> None:
    declared = {path.name for path in seed.ETC.glob("*.yml")}
    assert _linted_configs() == declared


def _tenant_configs() -> dict[str, dict[str, Any]]:
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in seed.ETC.glob("*.yml")
    }


def _backbone_blocks() -> dict[str, dict[str, Any]]:
    return {tenant: config["backbone"] for tenant, config in _tenant_configs().items()}


def _declared_coverage_targets() -> dict[str, int]:
    return {
        tenant: backbone["coverage_target_miles"]
        for tenant, backbone in _backbone_blocks().items()
    }


def _knob(urlopen_recorder: UrlopenRecorder, key: str) -> dict[str, Any]:
    return {
        tenant: document[key]
        for tenant, document in _written_by_tenant(urlopen_recorder, "knobs").items()
    }


def test_pipeline_writes_each_tenant_the_coverage_target_its_config_declares(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(urlopen_recorder, monkeypatch)
    assert _knob(urlopen_recorder, "backbone_coverage_target_miles") == \
        _declared_coverage_targets()


def test_pipeline_writes_no_knob_the_synthesizer_does_not_read(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(urlopen_recorder, monkeypatch)
    assert {
        frozenset(document)
        for document in _written_by_tenant(urlopen_recorder, "knobs").values()
    } == {frozenset({"backbone_coverage_target_miles"})}


def _configs_naming_a_providers_file() -> set[str]:
    return {
        tenant
        for tenant, config in _tenant_configs().items()
        if config.get("inputs", {}).get("providers")
    }


def test_pipeline_writes_every_tenant_the_regions_of_the_file_its_config_names(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(urlopen_recorder, monkeypatch)
    written = _written_by_tenant(urlopen_recorder, "provider-regions")
    seeded = sum(1 for regions in written.values() if regions)
    assert seeded == len(_configs_naming_a_providers_file())


def _declared_off_net_paths() -> set[str]:
    paths: set[str] = set()
    for config in seed.ETC.glob("*.yml"):
        declared = yaml.safe_load(config.read_text(encoding="utf-8"))
        forced = declared.get("inputs", {}).get("forced")
        if forced:
            paths.add(forced)
    return paths


def test_no_declared_off_net_seat_is_a_city_a_carrier_already_serves() -> None:
    carriers = _carrier_cities()
    overlapping = sorted(
        city
        for path in _declared_off_net_paths()
        for city in {_city_key(row) for row in _rows(REPO_ROOT / path)} & carriers
    )
    assert overlapping == []


def test_every_carrier_has_both_a_points_file_and_a_fiber_file() -> None:
    points = sorted(p.stem for p in (seed.DATA / "pops").glob("*.csv"))
    assert points == _carrier_names()


def _fiber_file(directory: str) -> Path:
    return seed.DATA / seed.FIBER_SEGMENTS / directory / "zayo.csv"


def _carrier_fiber_written(
    recorder: UrlopenRecorder, carrier: str
) -> list[dict[str, Any]]:
    return next(
        cast("list[dict[str, Any]]", json.loads(cast("bytes", request.data)))
        for request in recorder.requests
        if request.full_url.endswith(f"/carriers/{carrier}/fiber-segments")
    )


def test_push_carriers_marks_each_fiber_row_by_the_directory_it_came_out_of(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(urlopen_recorder, monkeypatch)
    written = _carrier_fiber_written(urlopen_recorder, "zayo")
    assert {
        water: sum(1 for row in written if row["submarine"] is water)
        for water in (False, True)
    } == {
        False: len(_rows(_fiber_file(seed.TERRESTRIAL))),
        True: len(_rows(_fiber_file(seed.SUBMARINE))),
    }


def _tenants_written(paths: list[str], resource: str) -> int:
    return sum(1 for path in paths if re.fullmatch(rf"tenants/[^/]+/{resource}", path))


@pytest.mark.parametrize("resource", ["forced-homes", "label", "provider-regions"])
def test_pipeline_writes_a_document_for_every_tenant(
        resource: str, urlopen_recorder: UrlopenRecorder,
        monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, resource) == len(list(seed.ETC.glob("*.yml")))


def _merged_carriers() -> tuple[list[Site], dict[tuple[str, str], FiberSegment]]:
    points = [
        row
        for path in sorted((seed.DATA / "pops").glob("*.csv"))
        for row in _rows(path)
    ]
    segments = [
        row
        for path in sorted((seed.DATA / seed.FIBER_SEGMENTS).glob("*/*.csv"))
        for row in _rows(path)
    ]
    return load_merged_carriers(points, segments)


def _cities_and_adjacency() -> tuple[dict[str, str], dict[str, list[tuple[str, float]]]]:
    sites, links = _merged_carriers()
    return {site.name: site.id for site in sites}, build_adjacency(links)


def _pinned_cities(backbone: dict[str, Any]) -> list[str]:
    return list((backbone.get("forced") or {}).get("nodes") or [])


def _exempt_cities(backbone: dict[str, Any]) -> list[str]:
    return list(backbone.get("degree_exempt") or [])


def _pinned_ids(backbone: dict[str, Any], by_name: dict[str, str]) -> tuple[str, ...]:
    return tuple(by_name[name] for name in _pinned_cities(backbone) if name in by_name)


def _path_endpoints(city_id: str, pinned: tuple[str, ...]) -> int:
    return len(pinned) - (1 if city_id in pinned else 0)


def _ceiling_bounds(
    cities: Callable[[dict[str, Any]], list[str]],
) -> list[tuple[str, str, int, int]]:
    by_name, adjacency = _cities_and_adjacency()
    bounds: list[tuple[str, str, int, int]] = []
    for tenant, backbone in sorted(_backbone_blocks().items()):
        pinned = _pinned_ids(backbone, by_name)
        asked = backbone["number_of_diverse_paths"]
        for city in cities(backbone):
            city_id = by_name.get(city)
            if city_id is None or _path_endpoints(city_id, pinned) < 1:
                continue
            ground = PathProofInputs(
                pinned, adjacency, asked, backbone["node_count"]["max"]
            )
            bound = independent_path_ceiling(city_id, ground)
            bounds.append((tenant, city, bound, asked))
    return bounds


def _exemption_ceiling_bounds() -> list[tuple[str, str, int, int]]:
    return _ceiling_bounds(_exempt_cities)


def test_no_tenant_exempts_a_city_its_own_fiber_already_accounts_for() -> None:
    assert [
        (tenant, city, bound, degree)
        for tenant, city, bound, degree in _exemption_ceiling_bounds()
        if bound < degree
    ] == []


def test_every_pinned_city_can_carry_the_diversity_its_tenant_asks_for() -> None:
    assert [
        (tenant, city, bound, asked)
        for tenant, city, bound, asked in _ceiling_bounds(_pinned_cities)
        if bound < asked
    ] == []


def _demand(config: dict[str, Any]) -> list[Site]:
    inputs = config["inputs"]
    providers = inputs.get("providers")
    places = load_sites(_mapping_rows(inputs.get("locations", {})))
    places += load_regions(_rows(REPO_ROOT / providers)) if providers else []
    return [place for place in places if not place.exempt_from_distance_constraint]


def _seats_for_coverage(config: dict[str, Any], carriers: list[Site]) -> int:
    target = config["backbone"]["coverage_target_miles"]
    places = _demand(config)
    reach = {
        carrier.name: {
            place.id for place in places if haversine_miles(place, carrier) <= target
        }
        for carrier in carriers
    }
    pinned = _pinned_cities(config["backbone"])
    unserved = {place.id for place in places}
    for city in pinned:
        unserved -= reach.get(city, set())
    seats = len(pinned)
    while unserved:
        best = max(reach.values(), key=lambda served: len(served & unserved))
        if not best & unserved:
            break
        unserved -= best
        seats += 1
    return seats


def _seat_shortfalls() -> list[tuple[str, int, int]]:
    carriers, _segments = _merged_carriers()
    shortfalls: list[tuple[str, int, int]] = []
    for tenant, config in sorted(_tenant_configs().items()):
        cap = config["backbone"]["node_count"]["max"]
        needed = _seats_for_coverage(config, carriers)
        if cap < needed:
            shortfalls.append((tenant, cap, needed))
    return shortfalls


def test_no_tenant_caps_its_backbone_below_the_coverage_target_it_asks_for() -> None:
    assert not _seat_shortfalls()
