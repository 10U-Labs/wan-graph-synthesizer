from __future__ import annotations

import sys
import urllib.error
import urllib.request
from email.message import Message
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
    _send,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")


def _one_carrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "Reston,Denver")
    _write_csv(
        tmp_path / "pops" / "lumen.csv",
        "Municipality,State", "Reston,VA", "Denver,CO")


def _fiberless_carrier(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", data)
    _write_csv(
        data / "pops" / "lumen.csv", "Municipality,State", "Reston,VA")


def _off_net_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *seats: str) -> str:
    _one_carrier(tmp_path / "data", monkeypatch)
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", *seats)
    return "offnet/off.csv"


def _one_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(
        tmp_path / "providers" / "providers.csv", "city,state", "Reston,VA")


def _one_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    _off_net_file(tmp_path, monkeypatch, "Link,TX")
    monkeypatch.setattr(seed, "ETC", tmp_path / "etc")
    _write_csv(tmp_path / "regions" / "providers.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "locations" / "f35.csv", "city,state", "Luke,AZ")
    (tmp_path / "etc").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc" / "f_35.yml").write_text(body, encoding="utf-8")


def _pushed_bodies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, put_recorder: CallRecorder,
        body: str = _TENANT_YML) -> dict[str, Any]:
    _one_tenant(tmp_path, monkeypatch, body)
    push_tenants("http://api")
    return dict(zip(put_recorder.nth(1), put_recorder.nth(2)))


def test_slug_replaces_underscores_with_hyphens() -> None:
    assert _slug("f_35") == "f-35"


def test_slug_leaves_a_plain_stem_unchanged() -> None:
    assert _slug("lumen") == "lumen"


def test_degree_doc_wraps_the_value_under_degree() -> None:
    assert _degree_doc(2) == {"degree": 2}


def test_rows_lowercases_the_header_keys(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    _write_csv(path, "City,State", "Reston,VA")
    assert set(_rows(path)[0]) == {"city", "state"}


def test_rows_parses_latitude_as_float(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    _write_csv(path, "city,latitude,longitude", "Reston,38.95,-77.34")
    assert _rows(path)[0]["latitude"] == 38.95


def test_rows_parses_longitude_as_float(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    _write_csv(path, "city,latitude,longitude", "Reston,38.95,-77.34")
    assert _rows(path)[0]["longitude"] == -77.34


def test_rows_strips_surrounding_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "v.csv"
    _write_csv(path, "city,state", " Reston , VA ")
    assert _rows(path)[0]["city"] == "Reston"


def test_rows_keeps_string_values_without_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    _write_csv(path, "a_city,z_city", "Reston,Denver")
    assert _rows(path)[0] == {"a_city": "Reston", "z_city": "Denver"}


def test_rows_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _rows(tmp_path / "missing.csv")


def test_mapping_rows_concatenates_list_values(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "b.csv", "city,state", "Denver,CO")
    assert len(_mapping_rows({"one": ["a.csv"], "two": ["b.csv"]})) == 2


def test_mapping_rows_accepts_a_scalar_value(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    assert len(_mapping_rows({"only": "a.csv"})) == 1


def test_mapping_rows_drops_the_grouping_labels(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "a.csv", "city,state", "Reston,VA")
    assert "group" not in _mapping_rows({"group": "a.csv"})[0]


def test_carrier_names_returns_sorted_stems(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "X,Y")
    _write_csv(tmp_path / "fiber_segments" / "cogent.csv", "a_city,z_city", "X,Y")
    assert _carrier_names() == ["cogent", "lumen"]


def test_carrier_names_ignores_non_csv_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "fiber_segments" / "lumen.csv", "a_city,z_city", "X,Y")
    (tmp_path / "fiber_segments" / "notes.txt").write_text("x", encoding="utf-8")
    assert _carrier_names() == ["lumen"]


def test_city_key_casefolds_the_municipality_and_state() -> None:
    assert _city_key({"municipality": "Dulles", "state": "VA"}) == ("dulles", "va")


def test_carrier_cities_collects_every_point_a_carrier_file_lists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _one_carrier(tmp_path, monkeypatch)
    assert _carrier_cities() == {("reston", "va"), ("denver", "co")}


def test_carrier_cities_ignores_a_carrier_with_no_fiber_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fiberless_carrier(tmp_path, monkeypatch)
    assert _carrier_cities() == set()


def test_carrier_cities_is_empty_without_any_carrier_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DATA", tmp_path)
    assert _carrier_cities() == set()


def test_off_net_rows_returns_every_seat_no_carrier_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _off_net_file(tmp_path, monkeypatch, "Dulles,VA", "Laurel,MT")
    assert len(_off_net_rows(path)) == 2


def test_off_net_rows_refuses_a_seat_a_carrier_already_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _off_net_file(tmp_path, monkeypatch, "Reston,VA")
    with pytest.raises(ValueError, match="Reston, VA"):
        _off_net_rows(path)


def test_off_net_rows_names_every_on_net_seat_it_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _off_net_file(tmp_path, monkeypatch, "Reston,VA", "Denver,CO")
    with pytest.raises(ValueError, match="Denver, CO; Reston, VA"):
        _off_net_rows(path)


def test_off_net_rows_refuses_a_seat_spelled_in_another_case(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _off_net_file(tmp_path, monkeypatch, "reston,va")
    with pytest.raises(ValueError, match="reston, va"):
        _off_net_rows(path)


def test_off_net_rows_accepts_a_seat_only_a_fiberless_carrier_has_a_point_in(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fiberless_carrier(tmp_path / "data", monkeypatch)
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", "Reston,VA")
    assert len(_off_net_rows("offnet/off.csv")) == 1


def test_off_net_rows_keeps_a_seat_whose_state_differs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _off_net_file(tmp_path, monkeypatch, "Reston,TX")
    assert _off_net_rows(path) == [{"municipality": "Reston", "state": "TX"}]


def _reset() -> ConnectionResetError:
    return ConnectionResetError(104, "Connection reset by peer")


def _not_found() -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://api/tenants", 404, "Not Found", Message(), None)


def _failing_urlopen(
        monkeypatch: pytest.MonkeyPatch, *failures: BaseException) -> UrlopenRecorder:
    recorder = UrlopenRecorder(body=b'[{"id": "f-35"}]', failures=failures)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


def _attempts_made(monkeypatch: pytest.MonkeyPatch, failure: BaseException) -> int:
    recorder = _failing_urlopen(monkeypatch, failure)
    try:
        _send("http://api", "tenants", "GET", None)
    except OSError:
        pass
    return len(recorder.requests)


@pytest.mark.usefixtures("instant_retry")
def test_send_returns_the_body_when_a_reset_connection_is_tried_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _failing_urlopen(monkeypatch, _reset())
    assert _send("http://api", "tenants", "GET", None) == b'[{"id": "f-35"}]'


@pytest.mark.usefixtures("instant_retry")
def test_send_tries_a_reset_connection_again_wherever_the_reset_was_raised(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _failing_urlopen(monkeypatch, urllib.error.URLError(_reset()))
    assert _send("http://api", "tenants", "GET", None) == b'[{"id": "f-35"}]'


@pytest.mark.usefixtures("instant_retry")
def test_send_raises_when_every_attempt_is_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _failing_urlopen(monkeypatch, _reset(), _reset())
    with pytest.raises(ConnectionResetError):
        _send("http://api", "tenants", "GET", None)


@pytest.mark.usefixtures("instant_retry")
def test_send_says_it_is_trying_a_reset_connection_again(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _failing_urlopen(monkeypatch, _reset())
    _send("http://api", "tenants", "GET", None)
    assert "connection reset" in capsys.readouterr().out


def test_send_makes_one_request_when_the_api_answers_first_time(
        urlopen_recorder: UrlopenRecorder) -> None:
    _send("http://api", "tenants", "GET", None)
    assert len(urlopen_recorder.requests) == 1


def test_send_does_not_try_an_http_error_again(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _attempts_made(monkeypatch, _not_found()) == 1


def test_send_does_not_try_a_url_error_that_is_not_a_reset_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert _attempts_made(monkeypatch, urllib.error.URLError("Name or service not known")) == 1


def test_put_uses_the_put_method(urlopen_recorder: UrlopenRecorder) -> None:
    _put("http://api", "carriers/lumen/pops", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].method == "PUT"


def test_put_targets_the_api_path(urlopen_recorder: UrlopenRecorder) -> None:
    _put("http://api", "carriers/lumen/pops", [])
    assert urlopen_recorder.requests[0].full_url == "http://api/carriers/lumen/pops"


def test_put_encodes_the_json_body(urlopen_recorder: UrlopenRecorder) -> None:
    _put("http://api", "carriers/lumen/pops", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].data == b'[{"city": "Reston"}]'


def test_put_sets_the_json_content_type(urlopen_recorder: UrlopenRecorder) -> None:
    _put("http://api", "carriers/lumen/pops", [])
    assert urlopen_recorder.requests[0].get_header("Content-type") == "application/json"


@pytest.mark.usefixtures("urlopen_recorder")
def test_put_prints_the_response_status(capsys: pytest.CaptureFixture[str]) -> None:
    _put("http://api", "carriers/lumen/pops", [])
    assert "-> 200" in capsys.readouterr().out


def test_post_uses_the_post_method(urlopen_recorder: UrlopenRecorder) -> None:
    _post("http://api", "carriers/merge")
    assert urlopen_recorder.requests[0].method == "POST"


def test_post_targets_the_api_path(urlopen_recorder: UrlopenRecorder) -> None:
    _post("http://api", "tenants/f-35/wan")
    assert urlopen_recorder.requests[0].full_url == "http://api/tenants/f-35/wan"


def test_post_sends_no_body(urlopen_recorder: UrlopenRecorder) -> None:
    _post("http://api", "carriers/merge")
    assert urlopen_recorder.requests[0].data == b""


@pytest.mark.usefixtures("urlopen_recorder")
def test_post_prints_the_response_status(capsys: pytest.CaptureFixture[str]) -> None:
    _post("http://api", "carriers/merge")
    assert "-> 200" in capsys.readouterr().out


def test_post_json_decodes_the_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", UrlopenRecorder(body=b'{"deleted": ["csps/a.json"]}'))
    assert _post_json("http://api", "store/prune") == {"deleted": ["csps/a.json"]}


def test_get_uses_the_get_method(urlopen_recorder: UrlopenRecorder) -> None:
    _get("http://api", "tenants")
    assert urlopen_recorder.requests[0].method == "GET"


def test_get_sends_no_body(urlopen_recorder: UrlopenRecorder) -> None:
    _get("http://api", "tenants")
    assert urlopen_recorder.requests[0].data is None


def test_get_decodes_the_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", UrlopenRecorder(body=b'[{"id": "f-35"}]'))
    assert _get("http://api", "tenants") == [{"id": "f-35"}]


def test_delete_uses_the_delete_method(urlopen_recorder: UrlopenRecorder) -> None:
    _delete("http://api", "tenants/f-35")
    assert urlopen_recorder.requests[0].method == "DELETE"


def test_push_carriers_puts_the_pops_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/pops" in put_recorder.nth(1)


def test_push_carriers_puts_the_fiber_segments_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/fiber-segments" in put_recorder.nth(1)


def test_push_providers_pushes_regions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    _one_provider(tmp_path, monkeypatch)
    push_providers("http://api")
    assert "providers/regions" in put_recorder.nth(1)


def test_push_tenants_puts_the_label_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    push_tenants("http://api")
    assert "tenants/f-35/label" in put_recorder.nth(1)


def test_push_tenants_puts_the_convergence_promotion_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/convergence-promotion"] == {"promote": False}


def test_push_tenants_puts_the_access_homing_degree_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/access-homing-degree"] == {"degree": 1}


def test_push_tenants_puts_the_backbone_number_of_diverse_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/backbone-number-of-diverse-paths"] == {"degree": 2}


def test_push_tenants_puts_the_backbone_node_count_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/backbone-node-count"] == {"max": 3, "min": 3}


def test_push_tenants_puts_the_forced_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-backbone-nodes"] == ["Luke, AZ"]


def test_push_tenants_puts_the_forced_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-paths"] == [
        {"source": "Luke, AZ", "target": "Nellis, NV"}]


def test_push_tenants_puts_the_forced_homes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/forced-homes"] == [
        {"source": "Kirtland, NM", "target": "Nellis, NV"}]


def test_push_tenants_puts_the_prohibited_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/prohibited-backbone-nodes"] == ["Link, TX"]


def test_push_tenants_puts_the_prohibited_paths_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/prohibited-paths"] == [
        {"source": "Luke, AZ", "target": "Link, TX"}]


def test_push_tenants_builds_the_knobs_document_from_the_coverage_target(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/knobs"]["backbone_coverage_target_miles"] == 500


def test_push_tenants_builds_the_knobs_document_from_the_backup_path_multiple(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/knobs"]["backbone_max_backup_path_multiple"] == 2.5


def test_push_tenants_puts_the_settings_document(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/settings"] == {"compass_sector_count": 4}


def test_push_tenants_puts_the_provider_regions_its_config_names(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/provider-regions"] == [{"city": "Reston", "state": "VA"}]


def test_push_tenants_uses_empty_provider_regions_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  providers: regions/providers.csv\n", ""))
    assert bodies["tenants/f-35/provider-regions"] == []


def test_push_tenants_reads_off_net_when_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/off-net"] == [{"municipality": "Link", "state": "TX"}]


@pytest.mark.usefixtures("put_recorder")
def test_push_tenants_refuses_an_off_net_seat_a_carrier_already_serves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    _write_csv(tmp_path / "offnet" / "off.csv", "Municipality,State", "Reston,VA")
    with pytest.raises(ValueError, match="Reston, VA"):
        push_tenants("http://api")


def test_push_tenants_puts_the_degree_exempt_backbone_nodes_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/degree-exempt-backbone-nodes"] == ["Nellis, NV"]


def test_push_tenants_puts_an_empty_degree_exempt_document_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  degree_exempt:\n    - Nellis, NV\n", ""))
    assert bodies["tenants/f-35/degree-exempt-backbone-nodes"] == []


def test_push_tenants_uses_empty_off_net_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  forced: offnet/off.csv\n", ""))
    assert bodies["tenants/f-35/off-net"] == []


def test_push_tenants_skips_empty_config_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    _one_tenant(tmp_path, monkeypatch, "\n")
    push_tenants("http://api")
    assert put_recorder.calls == []


@pytest.mark.usefixtures("put_recorder")
def test_push_tenants_returns_the_tenant_ids(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    assert push_tenants("http://api") == ["f-35"]


def _stored_tenants(monkeypatch: pytest.MonkeyPatch, *ids: str) -> None:
    listing = [{"id": tenant} for tenant in ids]
    monkeypatch.setattr(seed, "_get", lambda _api, _path: listing)


def test_prune_tenants_deletes_a_tenant_without_a_config(
        monkeypatch: pytest.MonkeyPatch, delete_recorder: CallRecorder) -> None:
    _stored_tenants(monkeypatch, "f-35-non-redundant")
    prune_tenants("http://api", ["f-35"])
    assert delete_recorder.calls == [("http://api", "tenants/f-35-non-redundant")]


def test_prune_tenants_keeps_a_tenant_with_a_config(
        monkeypatch: pytest.MonkeyPatch, delete_recorder: CallRecorder) -> None:
    _stored_tenants(monkeypatch, "f-35")
    prune_tenants("http://api", ["f-35"])
    assert delete_recorder.calls == []


@pytest.mark.usefixtures("delete_recorder")
def test_prune_tenants_names_the_tenant_it_deletes(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _stored_tenants(monkeypatch, "f-35-redundant")
    prune_tenants("http://api", [])
    assert "f-35-redundant" in capsys.readouterr().out


def test_build_merged_carriers_posts_the_merge(post_recorder: CallRecorder) -> None:
    build_merged_carriers("http://api")
    assert post_recorder.calls == [("http://api", "carriers/merge")]


def _prune_answering(
        monkeypatch: pytest.MonkeyPatch, deleted: list[str]) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    def _answer(api: str, path: str) -> dict[str, list[str]]:
        sent.append((api, path))
        return {"deleted": deleted}

    monkeypatch.setattr(seed, "_post_json", _answer)
    return sent


def test_prune_store_posts_the_prune(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _prune_answering(monkeypatch, [])
    prune_store("http://api")
    assert sent == [("http://api", "store/prune")]


def test_prune_store_names_every_key_that_went(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _prune_answering(monkeypatch, ["csps/aws/vertices.json"])
    prune_store("http://api")
    assert "deleted csps/aws/vertices.json" in capsys.readouterr().out


def test_prune_store_names_nothing_when_the_store_is_already_clean(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _prune_answering(monkeypatch, [])
    prune_store("http://api")
    assert "deleted " not in capsys.readouterr().out


def test_prune_store_survives_an_answer_it_does_not_recognise(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(seed, "_post_json", lambda _api, _path: [])
    prune_store("http://api")
    assert "deleted " not in capsys.readouterr().out


def test_build_tenants_posts_a_wan_build_for_each(post_recorder: CallRecorder) -> None:
    build_tenants("http://api", ["f-35", "minuteman"])
    assert post_recorder.nth(1) == ["tenants/f-35/wan", "tenants/minuteman/wan"]


def test_build_tenants_posts_nothing_without_tenants(post_recorder: CallRecorder) -> None:
    build_tenants("http://api", [])
    assert post_recorder.calls == []


def _run_main(
        monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[tuple[str, str]]:
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
    assert _run_main(monkeypatch, ["seed"])[0] == ("carriers", seed.DEFAULT_API)


def test_main_uses_the_cli_argument_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_main(monkeypatch, ["seed", "http://custom"])[0][1] == "http://custom"


def test_main_seeds_inputs_then_triggers_builds_in_order(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert [name for name, _ in _run_main(monkeypatch, ["seed"])] == [
        "carriers", "merge", "providers", "tenants", "prune", "prune-store", "build"]


def test_main_prunes_against_the_pushed_tenant_ids(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert ("prune", "t") in _run_main(monkeypatch, ["seed"])
