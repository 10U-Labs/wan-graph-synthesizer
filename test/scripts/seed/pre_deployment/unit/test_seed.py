"""Unit tests for the seed CLI helpers and push routines (fully isolated)."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import seed
from test_http_doubles import CallRecorder, UrlopenRecorder
from seed import (
    _carrier_cities,
    _carrier_names,
    _city_key,
    _degree_doc,
    _delete,
    _get,
    _mapping_rows,
    _off_net_rows,
    _post,
    _post_json,
    _put,
    _rows,
    _slug,
    build_merged_carriers,
    build_tenants,
    main,
    prune_store,
    prune_tenants,
    push_carriers,
    push_providers,
    push_tenants,
)

_TENANT_YML = """\
access:
  forced:
    homes:
      - source: Kirtland, NM
        target: Nellis, NV
  homing_degree: 1
backbone:
  coverage_target_miles: 500
  degree_exempt:
    - Nellis, NV
  forced:
    nodes:
      - Luke, AZ
    paths:
      - source: Luke, AZ
        target: Nellis, NV
  max_backup_path_multiple: 2.5
  node_count:
    max: 3
    min: 3
  number_of_diverse_paths: 2
  prohibited:
    nodes:
      - Link, TX
    paths:
      - source: Luke, AZ
        target: Link, TX
  promote_high_degree_convergences: false
inputs:
  forced: offnet/off.csv
  locations:
    F-35: locations/f35.csv
  providers: regions/providers.csv
label: F-35
settings:
  compass_sector_count: 4
"""


def _write_csv(path: Path, header: str, *rows: str) -> None:
    """Write a CSV with a *header* line and *rows* under *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")


def _one_carrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down one carrier's points and fiber segments under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "Reston,Denver")
    _write_csv(
        tmp_path / "pops" / "lumen.csv",
        "Municipality,State", "Reston,VA", "Denver,CO")


def _fiberless_carrier(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down one carrier's points with no fiber file, under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", data)
    _write_csv(
        data / "pops" / "lumen.csv", "Municipality,State", "Reston,VA")


def _off_net_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *seats: str) -> str:
    """Lay down an off-net file of *seats* beside one carrier's points; return its path."""
    _one_carrier(tmp_path / "data", monkeypatch)
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", *seats)
    return "offnet/off.csv"


def _one_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down the single provider regions file under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(
        tmp_path / "providers" / "providers.csv", "city,state", "Reston,VA")


def _one_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Lay down one tenant config *body* and its input files under temp roots."""
    _off_net_file(tmp_path, monkeypatch, "Link,TX")
    monkeypatch.setattr(seed, "ETC", tmp_path / "etc")
    _write_csv(tmp_path / "regions" / "providers.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "locations" / "f35.csv", "city,state", "Luke,AZ")
    (tmp_path / "etc").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc" / "f_35.yml").write_text(body, encoding="utf-8")


def _pushed_bodies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, put_recorder: CallRecorder,
        body: str = _TENANT_YML) -> dict[str, Any]:
    """Push one tenant config *body* and map each resource path to the document sent."""
    _one_tenant(tmp_path, monkeypatch, body)
    push_tenants("http://api")
    return dict(zip(put_recorder.nth(1), put_recorder.nth(2)))


def test_slug_replaces_underscores_with_hyphens() -> None:
    """_slug turns underscores into hyphens."""
    assert _slug("f_35") == "f-35"


def test_slug_leaves_a_plain_stem_unchanged() -> None:
    """_slug leaves a stem with no underscores unchanged."""
    assert _slug("lumen") == "lumen"


def test_degree_doc_wraps_the_value_under_degree() -> None:
    """_degree_doc wraps its argument as a degree document."""
    assert _degree_doc(2) == {"degree": 2}


def test_rows_lowercases_the_header_keys(tmp_path: Path) -> None:
    """_rows lowercases the CSV header keys."""
    path = tmp_path / "v.csv"
    _write_csv(path, "City,State", "Reston,VA")
    assert set(_rows(path)[0]) == {"city", "state"}


def test_rows_parses_latitude_as_float(tmp_path: Path) -> None:
    """_rows converts the latitude column to a float."""
    path = tmp_path / "v.csv"
    _write_csv(path, "city,latitude,longitude", "Reston,38.95,-77.34")
    assert _rows(path)[0]["latitude"] == 38.95


def test_rows_parses_longitude_as_float(tmp_path: Path) -> None:
    """_rows converts the longitude column to a float."""
    path = tmp_path / "v.csv"
    _write_csv(path, "city,latitude,longitude", "Reston,38.95,-77.34")
    assert _rows(path)[0]["longitude"] == -77.34


def test_rows_strips_surrounding_whitespace(tmp_path: Path) -> None:
    """_rows strips whitespace around values."""
    path = tmp_path / "v.csv"
    _write_csv(path, "city,state", " Reston , VA ")
    assert _rows(path)[0]["city"] == "Reston"


def test_rows_keeps_string_values_without_coordinates(tmp_path: Path) -> None:
    """_rows leaves values as strings when there is no latitude column."""
    path = tmp_path / "e.csv"
    _write_csv(path, "a_city,z_city", "Reston,Denver")
    assert _rows(path)[0] == {"a_city": "Reston", "z_city": "Denver"}


def test_rows_raises_for_a_missing_file(tmp_path: Path) -> None:
    """_rows raises ValueError when the file does not exist."""
    with pytest.raises(ValueError, match="does not exist"):
        _rows(tmp_path / "missing.csv")


def test_mapping_rows_concatenates_list_values(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_mapping_rows concatenates rows from every file in a list value."""
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "b.csv", "city,state", "Denver,CO")
    assert len(_mapping_rows({"one": ["a.csv"], "two": ["b.csv"]})) == 2


def test_mapping_rows_accepts_a_scalar_value(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_mapping_rows accepts a single file path given as a scalar."""
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    assert len(_mapping_rows({"only": "a.csv"})) == 1


def test_mapping_rows_drops_the_grouping_labels(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_mapping_rows discards the labels, keeping only row dicts."""
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    assert "group" not in _mapping_rows({"group": "a.csv"})[0]


def test_carrier_names_returns_sorted_stems(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_names returns the CSV stems under data/fiber_segments, sorted."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "X,Y")
    _write_csv(tmp_path / "fiber_segments" / "cogent.csv", "a_city,z_city", "X,Y")
    assert _carrier_names() == ["cogent", "lumen"]


def test_carrier_names_ignores_non_csv_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_names ignores files that are not CSVs."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "X,Y")
    (tmp_path / "fiber_segments" / "notes.txt").write_text("x", encoding="utf-8")
    assert _carrier_names() == ["lumen"]


def test_city_key_casefolds_the_municipality_and_state() -> None:
    """_city_key folds case, so two spellings of one city compare equal."""
    assert _city_key({"municipality": "Dulles", "state": "VA"}) == ("dulles", "va")


def test_carrier_cities_collects_every_point_a_carrier_file_lists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_cities keys every row of every carrier points file by city and state."""
    _one_carrier(tmp_path, monkeypatch)
    assert _carrier_cities() == {("reston", "va"), ("denver", "co")}


def test_carrier_cities_ignores_a_carrier_with_no_fiber_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier with points but no fiber file has no cities, because it is never pushed.

    push_carriers walks the fiber files, so such a carrier's points never reach the API,
    and synthesizer.codec drops a point no fiber segment touches in any case. Counting
    its cities as served would refuse an off-net seat over a point no synthesis can see.
    """
    _fiberless_carrier(tmp_path, monkeypatch)
    assert _carrier_cities() == set()


def test_carrier_cities_is_empty_without_any_carrier_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_cities is empty when no carrier points file exists."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    assert _carrier_cities() == set()


def test_off_net_rows_returns_every_seat_no_carrier_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_off_net_rows returns the file's rows when no seat is a carrier's city."""
    path = _off_net_file(tmp_path, monkeypatch, "Dulles,VA", "Laurel,MT")
    assert len(_off_net_rows(path)) == 2


def test_off_net_rows_refuses_a_seat_a_carrier_already_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_off_net_rows raises for a seat in a city a carrier already has a point in.

    Such a seat is one the file cannot deliver: the synthesizer seats the operator's
    pin on the real point and skips the row, so the promise is silently unkept.
    """
    path = _off_net_file(tmp_path, monkeypatch, "Reston,VA")
    with pytest.raises(ValueError, match="Reston, VA"):
        _off_net_rows(path)


def test_off_net_rows_names_every_on_net_seat_it_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal names every offending seat, so fixing one does not reveal the next."""
    path = _off_net_file(tmp_path, monkeypatch, "Reston,VA", "Denver,CO")
    with pytest.raises(ValueError, match="Denver, CO; Reston, VA"):
        _off_net_rows(path)


def test_off_net_rows_refuses_a_seat_spelled_in_another_case(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A seat differing from the carrier's city only in case is the same place."""
    path = _off_net_file(tmp_path, monkeypatch, "reston,va")
    with pytest.raises(ValueError, match="reston, va"):
        _off_net_rows(path)


def test_off_net_rows_accepts_a_seat_only_a_fiberless_carrier_has_a_point_in(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A seat stands where the only point in that city belongs to a carrier with no fiber."""
    _fiberless_carrier(tmp_path / "data", monkeypatch)
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", "Reston,VA")
    assert len(_off_net_rows("offnet/off.csv")) == 1


def test_off_net_rows_keeps_a_seat_whose_state_differs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A city name a carrier serves in another state is a different place, so it stays."""
    path = _off_net_file(tmp_path, monkeypatch, "Reston,TX")
    assert _off_net_rows(path) == [{"municipality": "Reston", "state": "TX"}]


def test_put_uses_the_put_method(urlopen_recorder: UrlopenRecorder) -> None:
    """_put issues an HTTP PUT."""
    _put("http://api", "carriers/lumen/pops", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].method == "PUT"


def test_put_targets_the_api_path(urlopen_recorder: UrlopenRecorder) -> None:
    """_put targets the api base joined with the resource path."""
    _put("http://api", "carriers/lumen/pops", [])
    assert urlopen_recorder.requests[0].full_url == "http://api/carriers/lumen/pops"


def test_put_encodes_the_json_body(urlopen_recorder: UrlopenRecorder) -> None:
    """_put sends the body as encoded JSON."""
    _put("http://api", "carriers/lumen/pops", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].data == b'[{"city": "Reston"}]'


def test_put_sets_the_json_content_type(urlopen_recorder: UrlopenRecorder) -> None:
    """_put sets a JSON content-type header."""
    _put("http://api", "carriers/lumen/pops", [])
    assert urlopen_recorder.requests[0].get_header("Content-type") == "application/json"


@pytest.mark.usefixtures("urlopen_recorder")
def test_put_prints_the_response_status(capsys: pytest.CaptureFixture[str]) -> None:
    """_put prints the response status."""
    _put("http://api", "carriers/lumen/pops", [])
    assert "-> 200" in capsys.readouterr().out


def test_post_uses_the_post_method(urlopen_recorder: UrlopenRecorder) -> None:
    """_post issues an HTTP POST."""
    _post("http://api", "carriers/merge")
    assert urlopen_recorder.requests[0].method == "POST"


def test_post_targets_the_api_path(urlopen_recorder: UrlopenRecorder) -> None:
    """_post targets the api base joined with the operation path."""
    _post("http://api", "tenants/f-35/wan")
    assert urlopen_recorder.requests[0].full_url == "http://api/tenants/f-35/wan"


def test_post_sends_no_body(urlopen_recorder: UrlopenRecorder) -> None:
    """_post sends an empty body (the build operation takes none)."""
    _post("http://api", "carriers/merge")
    assert urlopen_recorder.requests[0].data == b""


@pytest.mark.usefixtures("urlopen_recorder")
def test_post_prints_the_response_status(capsys: pytest.CaptureFixture[str]) -> None:
    """_post prints the response status."""
    _post("http://api", "carriers/merge")
    assert "-> 200" in capsys.readouterr().out


def test_post_json_decodes_the_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json returns the operation's answer decoded from JSON.

    The one POST whose answer is read rather than discarded: the store's prune names the
    keys it took out, and the seed prints them into the seeding job's log.
    """
    monkeypatch.setattr(
        urllib.request, "urlopen", UrlopenRecorder(body=b'{"deleted": ["csps/a.json"]}'))
    assert _post_json("http://api", "store/prune") == {"deleted": ["csps/a.json"]}


def test_get_uses_the_get_method(urlopen_recorder: UrlopenRecorder) -> None:
    """_get issues an HTTP GET."""
    _get("http://api", "tenants")
    assert urlopen_recorder.requests[0].method == "GET"


def test_get_sends_no_body(urlopen_recorder: UrlopenRecorder) -> None:
    """_get sends no request body (a read takes none)."""
    _get("http://api", "tenants")
    assert urlopen_recorder.requests[0].data is None


def test_get_decodes_the_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get returns the response body decoded from JSON."""
    monkeypatch.setattr(
        urllib.request, "urlopen", UrlopenRecorder(body=b'[{"id": "f-35"}]'))
    assert _get("http://api", "tenants") == [{"id": "f-35"}]


def test_delete_uses_the_delete_method(urlopen_recorder: UrlopenRecorder) -> None:
    """_delete issues an HTTP DELETE."""
    _delete("http://api", "tenants/f-35")
    assert urlopen_recorder.requests[0].method == "DELETE"


def test_push_carriers_puts_the_pops_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier sites."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/pops" in put_recorder.nth(1)


def test_push_carriers_puts_the_fiber_segments_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier links."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/fiber-segments" in put_recorder.nth(1)


def test_push_providers_pushes_regions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_providers PUTs the combined provider regions."""
    _one_provider(tmp_path, monkeypatch)
    push_providers("http://api")
    assert "providers/regions" in put_recorder.nth(1)


def test_push_tenants_puts_the_label_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants PUTs the tenant label."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    push_tenants("http://api")
    assert "tenants/f-35/label" in put_recorder.nth(1)


def test_push_tenants_puts_the_convergence_promotion_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants wraps the promotion flag as the convergence-promotion document."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/convergence-promotion"] == {"promote": False}


def test_push_tenants_puts_the_access_homing_degree_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the homing degree from the access block, not a root key."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/access-homing-degree"] == {"degree": 1}


def test_push_tenants_puts_the_backbone_number_of_diverse_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the diverse path count from the backbone block, not a root key."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/backbone-number-of-diverse-paths"] == {"degree": 2}


def test_push_tenants_puts_the_backbone_node_count_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the node count bounds from the backbone block."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/backbone-node-count"] == {"max": 3, "min": 3}


def test_push_tenants_puts_the_forced_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the pinned nodes from the backbone block's forced pair."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-backbone-nodes"] == ["Luke, AZ"]


def test_push_tenants_puts_the_forced_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the pinned paths from the backbone block's forced pair."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-paths"] == [
        {"source": "Luke, AZ", "target": "Nellis, NV"}]


def test_push_tenants_puts_the_forced_homes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the pinned homes from the access block's forced pair.

    Every config ships this list empty, so the fixture populates it: an access link the
    operator pins onto a named backbone node is a working path, and an empty list in all
    five configs is what would let it rot with nothing going red.
    """
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-homes"] == [
        {"source": "Kirtland, NM", "target": "Nellis, NV"}]


def test_push_tenants_puts_the_prohibited_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the pruned nodes from the backbone block's prohibited pair."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/prohibited-backbone-nodes"] == ["Link, TX"]


def test_push_tenants_puts_the_prohibited_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the pruned paths from the backbone block's prohibited pair."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/prohibited-paths"] == [
        {"source": "Luke, AZ", "target": "Link, TX"}]


def test_push_tenants_builds_the_knobs_document_from_the_coverage_target(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants spells the stored knobs key out from the block's coverage target."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/knobs"]["backbone_coverage_target_miles"] == 500


def test_push_tenants_builds_the_knobs_document_from_the_backup_path_multiple(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants spells the stored knobs key out from the block's backup path multiple.

    A fractional multiple in the fixture, since the config layer accepts one where it refuses
    a fractional coverage target: the number multiplies a distance rather than standing in
    for one.
    """
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/knobs"]["backbone_max_backup_path_multiple"] == 2.5


def test_push_tenants_puts_the_settings_document(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends the tenant's settings block as its own document."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/settings"] == {"compass_sector_count": 4}


def test_push_tenants_puts_the_provider_regions_its_config_names(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the provider regions from the bare path the config names."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/provider-regions"] == [{"city": "Reston", "state": "VA"}]


def test_push_tenants_reads_off_net_when_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends the off-net rows when an off_net file is given."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/off-net"] == [{"municipality": "Link", "state": "TX"}]


@pytest.mark.usefixtures("put_recorder")
def test_push_tenants_refuses_an_off_net_seat_a_carrier_already_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """push_tenants stops rather than storing an off-net file naming an on-net city."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", "Reston,VA")
    with pytest.raises(ValueError, match="Reston, VA"):
        push_tenants("http://api")


def test_push_tenants_puts_the_degree_exempt_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the exempt nodes from the backbone block's degree_exempt key."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/degree-exempt-backbone-nodes"] == ["Nellis, NV"]


def test_push_tenants_puts_an_empty_degree_exempt_document_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """A config naming no exempt node still gets the resource, holding an empty list."""
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  degree_exempt:\n    - Nellis, NV\n", ""))
    assert bodies["tenants/f-35/degree-exempt-backbone-nodes"] == []


def test_push_tenants_uses_empty_off_net_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends an empty off-net list when no forced file is given."""
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  forced: offnet/off.csv\n", ""))
    assert bodies["tenants/f-35/off-net"] == []


def test_push_tenants_skips_empty_config_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants skips a tenant file that has no content."""
    _one_tenant(tmp_path, monkeypatch, "\n")
    push_tenants("http://api")
    assert put_recorder.calls == []


@pytest.mark.usefixtures("put_recorder")
def test_push_tenants_returns_the_tenant_ids(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """push_tenants returns the id of every tenant it pushed."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    assert push_tenants("http://api") == ["f-35"]


def _stored_tenants(monkeypatch: pytest.MonkeyPatch, *ids: str) -> None:
    """Stub the tenant listing the API answers with as *ids*."""
    listing = [{"id": tenant} for tenant in ids]
    monkeypatch.setattr(seed, "_get", lambda _api, _path: listing)


def test_prune_tenants_deletes_a_tenant_without_a_config(
        monkeypatch: pytest.MonkeyPatch, delete_recorder: CallRecorder) -> None:
    """prune_tenants DELETEs a stored tenant that etc/ no longer declares."""
    _stored_tenants(monkeypatch, "f-35-non-redundant")
    prune_tenants("http://api", ["f-35"])
    assert delete_recorder.calls == [("http://api", "tenants/f-35-non-redundant")]


def test_prune_tenants_keeps_a_tenant_with_a_config(
        monkeypatch: pytest.MonkeyPatch, delete_recorder: CallRecorder) -> None:
    """prune_tenants leaves a stored tenant that etc/ still declares."""
    _stored_tenants(monkeypatch, "f-35")
    prune_tenants("http://api", ["f-35"])
    assert delete_recorder.calls == []


@pytest.mark.usefixtures("delete_recorder")
def test_prune_tenants_names_the_tenant_it_deletes(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """prune_tenants names each tenant it removes, so the deletion is not silent."""
    _stored_tenants(monkeypatch, "f-35-redundant")
    prune_tenants("http://api", [])
    assert "f-35-redundant" in capsys.readouterr().out


def test_build_merged_carriers_posts_the_merge(post_recorder: CallRecorder) -> None:
    """build_merged_carriers POSTs the carrier merge."""
    build_merged_carriers("http://api")
    assert post_recorder.calls == [("http://api", "carriers/merge")]


def _prune_answering(
        monkeypatch: pytest.MonkeyPatch, deleted: list[str]) -> list[tuple[str, str]]:
    """Have the prune endpoint answer with ``deleted``; return the calls it was sent."""
    sent: list[tuple[str, str]] = []

    def _answer(api: str, path: str) -> dict[str, list[str]]:
        sent.append((api, path))
        return {"deleted": deleted}

    monkeypatch.setattr(seed, "_post_json", _answer)
    return sent


def test_prune_store_posts_the_prune(monkeypatch: pytest.MonkeyPatch) -> None:
    """prune_store POSTs the store prune."""
    sent = _prune_answering(monkeypatch, [])
    prune_store("http://api")
    assert sent == [("http://api", "store/prune")]


def test_prune_store_names_every_key_that_went(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Somebody reading the seeding job's log sees what went, not how much."""
    _prune_answering(monkeypatch, ["csps/aws/vertices.json"])
    prune_store("http://api")
    assert "deleted csps/aws/vertices.json" in capsys.readouterr().out


def test_prune_store_names_nothing_when_the_store_is_already_clean(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Every run after the first has nothing to take out and says nothing went."""
    _prune_answering(monkeypatch, [])
    prune_store("http://api")
    assert "deleted " not in capsys.readouterr().out


def test_prune_store_survives_an_answer_it_does_not_recognise(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The store has already pruned by then, so an odd answer costs the log line only.

    The localhost stub the integration tier drives the seed against answers every POST with
    one canned listing, which is exactly the shape this must not die on.
    """
    monkeypatch.setattr(seed, "_post_json", lambda _api, _path: [])
    prune_store("http://api")
    assert "deleted " not in capsys.readouterr().out


def test_build_tenants_posts_a_wan_build_for_each(post_recorder: CallRecorder) -> None:
    """build_tenants POSTs a WAN build for every tenant id."""
    build_tenants("http://api", ["f-35", "minuteman"])
    assert post_recorder.nth(1) == ["tenants/f-35/wan", "tenants/minuteman/wan"]


def test_build_tenants_posts_nothing_without_tenants(post_recorder: CallRecorder) -> None:
    """build_tenants makes no request when there are no tenants."""
    build_tenants("http://api", [])
    assert post_recorder.calls == []


def _run_main(
        monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[tuple[str, str]]:
    """Run main() with every step stubbed and *argv*; return the (name, api) calls."""
    calls: list[tuple[str, str]] = []

    def _push_tenants(api: str) -> list[str]:
        calls.append(("tenants", api))
        return ["t"]

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(seed, "push_carriers", lambda api: calls.append(("carriers", api)))
    monkeypatch.setattr(seed, "build_merged_carriers", lambda api: calls.append(("merge", api)))
    monkeypatch.setattr(seed, "push_providers", lambda api: calls.append(("providers", api)))
    monkeypatch.setattr(seed, "push_tenants", _push_tenants)
    monkeypatch.setattr(
        seed, "prune_tenants",
        lambda _api, tenants: calls.append(("prune", ",".join(tenants))))
    monkeypatch.setattr(
        seed, "prune_store", lambda api: calls.append(("prune-store", api)))
    monkeypatch.setattr(
        seed, "build_tenants", lambda api, _tenants: calls.append(("build", api)))
    main()
    return calls


def test_main_defaults_to_the_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """main targets the default public API when given no argument."""
    assert _run_main(monkeypatch, ["seed"])[0] == ("carriers", seed.DEFAULT_API)


def test_main_uses_the_cli_argument_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """main targets the API URL passed on the command line."""
    assert _run_main(monkeypatch, ["seed", "http://custom"])[0][1] == "http://custom"


def test_main_seeds_inputs_then_triggers_builds_in_order(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """main seeds carriers, merges them, seeds providers and tenants, then builds."""
    assert [name for name, _ in _run_main(monkeypatch, ["seed"])] == [
        "carriers", "merge", "providers", "tenants", "prune", "prune-store", "build"]


def test_main_prunes_against_the_pushed_tenant_ids(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """main hands the ids it just pushed to the prune step, as the roster to keep."""
    assert ("prune", "t") in _run_main(monkeypatch, ["seed"])
