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
from urllib.parse import urlsplit
from collections.abc import Callable
from typing import Any, cast

import pytest
import yaml

import seed
from repo_utils import REPO_ROOT
from seed import _carrier_cities, _carrier_names, _city_key, _mapping_rows, _rows, _slug
from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    independent_path_ceiling,
)
from synthesizer.codec import load_merged_carriers, load_regions, load_sites
from synthesizer.graphs import build_adjacency, distances_from
from synthesizer.input_graph import FiberSegment, Site, haversine_miles
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
    prefix = f"{urlsplit(seed.DEFAULT_API).path}/"
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
    """Seeding the real inputs writes at least one carrier's PoPs."""
    paths = _seed(urlopen_recorder, monkeypatch)
    assert any(re.fullmatch(r"carriers/[^/]+/pops", path) for path in paths)


def _backbone_keys_seed_reads() -> set[str]:
    """Every key under ``backbone:`` that ``scripts/seed.py`` looks up by name.

    Read off the source rather than listed here, so the contract cannot drift from the
    pushes it is about.
    """
    source = (REPO_ROOT / "scripts" / "seed.py").read_text(encoding="utf-8")
    return set(re.findall(r'backbone(?:\[|\.get\()"([^"]+)"', source))


def test_no_tenant_declares_a_backbone_key_the_seed_does_not_read() -> None:
    """Every key under ``backbone:`` in every config is one the seed pushes somewhere.

    A key the program stopped reading is a setting an operator can still write and watch
    do nothing, which is how the data-center gate stayed in all five configs long after
    nothing turned it on.
    """
    declared: set[str] = set()
    for config in sorted((REPO_ROOT / "etc").glob("*.yml")):
        declared |= set(yaml.safe_load(config.read_text(encoding="utf-8"))["backbone"])
    assert declared <= _backbone_keys_seed_reads()


def test_yamllint_names_every_tenant_config() -> None:
    """The workflow's yamllint file list names exactly the configs the roster declares."""
    declared = {path.name for path in seed.ETC.glob("*.yml")}
    assert _linted_configs() == declared


def _tenant_configs() -> dict[str, dict[str, Any]]:
    """The whole config git holds for each tenant, keyed by the tenant id seed derives."""
    return {
        _slug(path.stem): yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in seed.ETC.glob("*.yml")
    }


def _backbone_blocks() -> dict[str, dict[str, Any]]:
    """Each tenant's whole ``backbone`` block, keyed by the tenant id seed derives.

    Every backbone knob a contract here asserts on is read through this one place, so a
    test names the key it means and nothing re-opens the config files to find it.
    """
    return {tenant: config["backbone"] for tenant, config in _tenant_configs().items()}


def _declared_coverage_targets() -> dict[str, int]:
    """Each tenant's coverage target, read from the backbone block of its own config."""
    return {
        tenant: backbone["coverage_target_miles"]
        for tenant, backbone in _backbone_blocks().items()
    }


def _declared_backup_path_multiples() -> dict[str, float]:
    """Each tenant's backup path multiple, read from the backbone block of its own config."""
    return {
        tenant: backbone["max_backup_path_multiple"]
        for tenant, backbone in _backbone_blocks().items()
    }


def _knob(urlopen_recorder: UrlopenRecorder, key: str) -> dict[str, Any]:
    """One key of every tenant's written knobs document, by tenant."""
    return {
        tenant: document[key]
        for tenant, document in _written_by_tenant(urlopen_recorder, "knobs").items()
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
    assert _knob(urlopen_recorder, "backbone_coverage_target_miles") == \
        _declared_coverage_targets()


def test_pipeline_writes_each_tenant_the_backup_path_multiple_its_config_declares(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each knobs document carries the multiple its config declares, under the stored key.

    The same two-spellings problem as the coverage target, and the same reason it cannot be
    checked in either file alone: the config names it ``backbone.max_backup_path_multiple``
    and the synthesizer reads ``backbone_max_backup_path_multiple``. A tenant whose
    multiple never arrives is a failed build rather than a synthesis that quietly paths the
    long way, since the synthesizer requires the key, but the failure would name the store
    and not this seam.
    """
    _seed(urlopen_recorder, monkeypatch)
    assert _knob(urlopen_recorder, "backbone_max_backup_path_multiple") == \
        _declared_backup_path_multiples()


def test_pipeline_writes_no_knob_the_synthesizer_does_not_read(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """The knobs document carries the two keys the synthesizer reads and nothing else.

    Asserted over the key set rather than tenant by tenant: a knob written here and read
    nowhere steers nothing, and one the seed tool stops writing is a required key the
    synthesizer will refuse the build for.
    """
    _seed(urlopen_recorder, monkeypatch)
    assert {
        frozenset(document)
        for document in _written_by_tenant(urlopen_recorder, "knobs").values()
    } == {frozenset({"backbone_coverage_target_miles", "backbone_max_backup_path_multiple"})}


def _configs_naming_a_providers_file() -> set[str]:
    """The tenant ids whose config names a regions file under ``inputs.providers``.

    A tenant with no cloud demand names none and is seeded an empty document, so the
    roster is no longer the count of tenants that end up with regions. etc/yurop.yml is
    that tenant: its five sites are the whole of its demand.
    """
    return {
        tenant
        for tenant, config in _tenant_configs().items()
        if config.get("inputs", {}).get("providers")
    }


def test_pipeline_writes_every_tenant_the_regions_of_the_file_its_config_names(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every tenant naming a regions file is seeded regions from the bare path it names.

    The config names the file and only the file holds the rows, so neither side says
    alone that a tenant ends up with any regions at all. A shape the reader mishandles
    is the failure this catches: it delivers an empty document rather than an error, and
    a tenant seeded no regions has no cloud demand to home. A tenant that names no file
    is excused, because an empty document is then the answer its config asked for.
    """
    _seed(urlopen_recorder, monkeypatch)
    written = _written_by_tenant(urlopen_recorder, "provider-regions")
    seeded = sum(1 for regions in written.values() if regions)
    assert seeded == len(_configs_naming_a_providers_file())


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


def test_every_carrier_has_both_a_points_file_and_a_fiber_file() -> None:
    """Every carrier the maps declare is declared in both directories, not one.

    A carrier is two files, and seed reads the roster off the fiber files alone. A
    points file with no fiber file beside it is a carrier nothing pushes, whose cities
    would still have to be kept out of the off-net seats by hand; a fiber file with no
    points file stops the seed outright at _rows. This fails on the commit that adds
    half a carrier rather than leaving it to surface as a refused tenant config.
    """
    points = sorted(p.stem for p in (seed.DATA / "pops").glob("*.csv"))
    assert points == _carrier_names()


def _tenants_written(paths: list[str], resource: str) -> int:
    """How many tenants seed wrote *resource* for, over the paths it requested."""
    return sum(1 for path in paths if re.fullmatch(rf"tenants/[^/]+/{resource}", path))


def test_pipeline_writes_a_label_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a label resource for every tenant config file."""
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, "label") == len(list(seed.ETC.glob("*.yml")))


def test_pipeline_writes_a_provider_regions_document_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a provider-regions resource for every tenant config file.

    A tenant naming no regions file is seeded an empty list, which is exactly the state
    that would hide a tenant seeded without the document at all -- and the synthesizer
    reads its config resources unconditionally, so a tenant missing one gets no WAN
    rather than a default.
    """
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, "provider-regions") == len(list(seed.ETC.glob("*.yml")))


def test_pipeline_writes_a_forced_homes_document_for_every_tenant(
        urlopen_recorder: UrlopenRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeding writes a forced-homes resource for every tenant config file.

    The list is empty in every config, which is exactly the state that would hide a
    tenant seeded without the document at all -- and the synthesizer reads its config
    resources unconditionally, so a tenant missing one gets no WAN rather than a default.
    """
    paths = _seed(urlopen_recorder, monkeypatch)
    assert _tenants_written(paths, "forced-homes") == len(list(seed.ETC.glob("*.yml")))


def _merged_carriers() -> tuple[list[Site], dict[tuple[str, str], FiberSegment]]:
    """Every carrier's points and every carrier's fiber, merged as the API merges them.

    Read with seed's own reader and merged by the same loader, so the graph measured here
    is the graph the synthesizer starts from. The files are taken in sorted order because
    a generated id depends on what claimed the name first.
    """
    points = [
        row
        for path in sorted((seed.DATA / "pops").glob("*.csv"))
        for row in _rows(path)
    ]
    segments = [
        row for path in sorted((seed.DATA / "fiber_segments").glob("*.csv")) for row in _rows(path)
    ]
    return load_merged_carriers(points, segments)


def _cities_and_adjacency() -> tuple[dict[str, str], dict[str, list[tuple[str, float]]]]:
    """The merged carriers: their cities by display name, and their fiber adjacency.

    The mapping back from a config's ``City, ST`` spelling to a generated id is what the
    callers below need, since a config names cities and the graph is keyed by id.
    """
    sites, links = _merged_carriers()
    return {site.name: site.id for site in sites}, build_adjacency(links)


def _pinned_cities(backbone: dict[str, Any]) -> list[str]:
    """The cities a tenant pins into its backbone, as its config spells them."""
    return list((backbone.get("forced") or {}).get("nodes") or [])


def _exempt_cities(backbone: dict[str, Any]) -> list[str]:
    """The cities a tenant excuses the diverse path count, as its config spells them."""
    return list(backbone.get("degree_exempt") or [])


def _pinned_ids(backbone: dict[str, Any], by_name: dict[str, str]) -> tuple[str, ...]:
    """The tenant's pinned backbone cities as site ids, skipping any it has no point for.

    A pin the carrier files do not serve is seated by fabricating a point for it, which this
    graph does not have. Leaving it out costs the count a place a path could have ended,
    which can only make the bound below smaller.
    """
    return tuple(by_name[name] for name in _pinned_cities(backbone) if name in by_name)


def _path_endpoints(city_id: str, pinned: tuple[str, ...]) -> int:
    """How many places a path out of ``city_id`` has to end at, for the bound below.

    The bound counts paths to the tenant's pinned cities, so the pins are the only
    endpoints there are, and a city that is itself a pin cannot path to itself. A tenant
    that pins one city therefore leaves a path out of it nowhere to go.
    """
    return len(pinned) - (1 if city_id in pinned else 0)


def _ceiling_bounds(
    cities: Callable[[dict[str, Any]], list[str]],
) -> list[tuple[str, str, int, int]]:
    """Per tenant, each named city's ceiling lower bound beside the number it asks for.

    ``cities`` picks which of a tenant's cities to measure, which is the only thing the two
    contracts below differ in: one asks about the cities a tenant excuses, the other about
    the cities it pins.

    The bound counts paths from the city to the tenant's pinned backbone cities that share
    no city on the way, over the merged carriers. It is a floor rather than the
    real ceiling for two reasons, and both point the same way: the real run seats backbone
    nodes beyond the pins, which gives paths more distinct places to end, and it fabricates
    on-net points and seats off-net ones, which adds fiber segments. Neither can lower a maximum
    flow, so the real ceiling is at least what this returns.

    A city the carrier files hold no point for is left out, since there is no graph to
    measure it on and a silent zero would read as a proven limit.

    A city with no other pin to path to at all is left out for the same reason: every path
    counted here ends at one of the tenant's pins, so a city that is the only pin leaves a
    path out of it nowhere to go and the bound reads zero however much fiber leaves the
    city. That is a fact about the config rather than about the ground. Two-Node was in that
    position while it pinned Ashburn, VA alone, and pinning Salt Lake City, UT beside it
    brought both cities back into the count.

    Having fewer pins than the number asked for is no longer a reason to leave a city out.
    A peer may carry more than one path where the tenant's own seats leave its sites too
    few peers to reach (see ``synthesizer.ceiling.paths_per_peer``), so the tenant's number
    and its seat cap are both passed in and a two-seat tenant asking for two paths is
    measured on whether its fiber joins the two cities two ways rather than skipped for
    having pinned only two. Two-Node is that tenant, and the seat cap is what the build
    reads, so measuring without it would hold a city to a bound the synthesis never applies.

    What keeps a pin honest while it is the only one is the synthesizer itself, which seats
    a pin only where the carrier graph gives it two links (``compute_eligible_backbone_ids``)
    and refuses one sitting in a fiber pocket too small for the backbone it was asked for
    (``forced_backbone_resilience_error``).

    The tenant's own backup path multiple is applied, because the real run applies it: a
    ceiling measured over fiber the synthesis may not use is not a floor under the real one
    but a number above it, and a tenant could clear this contract on paths its build would
    refuse. Adding pins can only admit more fiber segments, since a segment is withheld only when no
    peer at all can reach it inside its budget, so the bound stays a floor under the real
    ceiling exactly as before.
    """
    by_name, adjacency = _cities_and_adjacency()
    bounds: list[tuple[str, str, int, int]] = []
    for tenant, backbone in sorted(_backbone_blocks().items()):
        pinned = _pinned_ids(backbone, by_name)
        measured = [by_name[city] for city in cities(backbone) if city in by_name]
        asked = backbone["number_of_diverse_paths"]
        # A row per peer and per city measured: an exempt city need not be a pin, and the
        # bound is measured from it as well as to it.
        limit = BackupPathLimit(
            float(backbone["max_backup_path_multiple"]),
            distances_from(adjacency, {*pinned, *measured}),
        )
        for city in cities(backbone):
            city_id = by_name.get(city)
            if city_id is None or _path_endpoints(city_id, pinned) < 1:
                continue
            ground = PathProofInputs(
                pinned, adjacency, limit, asked, backbone["node_count"]["max"]
            )
            bound = independent_path_ceiling(city_id, ground)
            bounds.append((tenant, city, bound, asked))
    return bounds


def _exemption_ceiling_bounds() -> list[tuple[str, str, int, int]]:
    """Every exempt city's ceiling lower bound beside the number its tenant asks for."""
    return _ceiling_bounds(_exempt_cities)


def test_no_tenant_exempts_a_city_its_own_fiber_already_accounts_for() -> None:
    """No exempt city is one whose ceiling would have lowered its target anyway.

    Neither file settles this alone: the config says which cities are excused the degree,
    and only the carrier files say which of them could have met it. A city that cannot is
    held to what its fiber carries and passes on that, so excusing it changes no outcome
    and costs the report the line that would have explained the synthesis. A city that can is
    a different matter, and the exemption is then the only reason a real shortfall goes
    unmentioned -- so an exemption is worth keeping only where the fiber does not already
    account for the gap.

    Boston was a city of the first kind: every path out of it passes through Albany or
    Stamford, so it could never hold three independent links, and it came off the list once
    the ceiling said so. San Jose is a city of the second kind, with three paths to three
    different pinned cities that share no city between them.
    """
    assert [
        (tenant, city, bound, degree)
        for tenant, city, bound, degree in _exemption_ceiling_bounds()
        if bound < degree
    ] == []


def test_every_pinned_city_can_carry_the_diversity_its_tenant_asks_for() -> None:
    """No tenant pins a backbone city whose own fiber cannot hold the paths it asks for.

    The base backbone is now ranked by how many diverse paths a site's fiber can carry
    rather than by how many fiber segments touch it, which makes this the question the ranking is
    trying to answer -- and a pin is the one site the ranking never gets to decide, because
    an operator has already decided it. So a pin is the place a synthesis can still start out
    short, and neither file can say on its own: the config names the cities, the carrier
    files say what their fiber does.

    Measured over the merged carriers today, seven of the thirty-five pinned cities sit
    exactly on the number their tenant asks for and the other twenty-eight are above it --
    Boston, MA under both DAF and DoW, F-35's Ashburn, VA, Hillsboro, OR and Seattle, WA,
    each with two paths out that share no city, and Two-Node's Ashburn, VA and Salt Lake
    City, UT, joined by two paths sharing nothing but their two ends, 1,843.1 and 2,041.1
    miles against 1,815.7 direct. The bound counts only paths to the tenant's other pins, so
    the real run, which seats more sites and adds fiber segments, can only do better.

    A tenant that pins one city is not measured here (see :func:`_ceiling_bounds`), because
    a path out of it would have nowhere to end and the bound would report the count of pins
    rather than anything about the fiber. No tenant is in that position today; Two-Node was,
    until it pinned a second city.
    """
    assert [
        (tenant, city, bound, asked)
        for tenant, city, bound, asked in _ceiling_bounds(_pinned_cities)
        if bound < asked
    ] == []


def _demand(config: dict[str, Any]) -> list[Site]:
    """A tenant's demand the coverage target applies to: its own sites and its cloud regions.

    Loaded through the synthesizer's own readers, so the exemption that excuses an OCONUS
    site the target is the one the coverage pass honours rather than a second reading of the
    same column. Off-net candidates are not here: they are seats the synthesis may fabricate,
    not places asking to be served.
    """
    inputs = config["inputs"]
    providers = inputs.get("providers")
    places = load_sites(_mapping_rows(inputs.get("locations", {})))
    places += load_regions(_rows(REPO_ROOT / providers)) if providers else []
    return [place for place in places if not place.exempt_from_distance_constraint]


def _seats_for_coverage(config: dict[str, Any], carriers: list[Site]) -> int:
    """How many backbone seats a tenant's own coverage target needs before it is met.

    The pinned cities are seated first, since the synthesis has no choice about them, and
    carrier points are then taken greedily, each round the point that brings in the most
    places still outside the target. Greedy returns an upper bound on the smallest such
    set, which is the direction that matters: a tenant whose cap clears this number
    genuinely has the room, so no tenant is failed for a cap that would have sufficed.

    A place beyond the target from every carrier point cannot be brought in by any seat,
    and the count stops rather than looping. That leaves the answer short, so a tenant with
    demand the maps cannot reach at all passes here and is a question for whoever put the
    place on the map.
    """
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
    """Per tenant, the seat cap beside the seats its target needs, where the cap is smaller."""
    carriers, _segments = _merged_carriers()
    shortfalls: list[tuple[str, int, int]] = []
    for tenant, config in sorted(_tenant_configs().items()):
        cap = config["backbone"]["node_count"]["max"]
        needed = _seats_for_coverage(config, carriers)
        if cap < needed:
            shortfalls.append((tenant, cap, needed))
    return shortfalls


def test_no_tenant_caps_its_backbone_below_the_coverage_target_it_asks_for() -> None:
    """No tenant caps its backbone below the seats its own coverage target would need.

    A tenant states two things that have to agree, and neither file settles it alone: the
    config sets the target and the seat cap, and only the carrier maps say how many points
    it takes to bring every site inside that distance. Where the cap is the smaller of the
    two the coverage pass runs out of seats before it runs out of target, and the synthesis it
    publishes misses by whatever the pins happened to leave. Nothing objects, because both
    numbers are legal on their own and the synthesis is the honest answer to the pair.

    Minuteman was the tenant that failed this. It pinned six cities into a backbone capped
    at six and asked for 400 miles, so the coverage pass began with no seat to spend and
    ended 484 miles out, while the greedy cover says nine seats would have done it and no
    place it serves is more than 37.7 miles from some carrier point. Its target was raised
    to what the six pinned cities deliver rather than its cap being raised to the target.
    """
    assert not _seat_shortfalls()
