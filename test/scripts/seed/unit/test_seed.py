"""Unit tests for the seed CLI helpers and push routines (fully isolated)."""

from __future__ import annotations

from pathlib import Path

import pytest

import seed
from http_test_doubles import CallRecorder, UrlopenRecorder
from seed import (
    _carrier_names,
    _degree_doc,
    _mapping_rows,
    _put,
    _rows,
    _slug,
    main,
    push_carriers,
    push_csps,
    push_tenants,
)

_TENANT_YML = """\
access_homing_degree: 1
aggregation_homing_degree: 1
core_mesh_degree: 2
core_node_count:
  max: 3
  min: 3
inputs:
  csps:
    AWS:
      - regions/aws.csv
  locations:
    F-35: locations/f35.csv
  off_net: offnet/off.csv
label: F-35
"""


def _write_csv(path: Path, header: str, *rows: str) -> None:
    """Write a CSV with a *header* line and *rows* under *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8")


def _one_carrier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down one carrier's points and connections under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "edges" / "lumen.csv", "a_city,z_city", "Reston,Denver")
    _write_csv(
        tmp_path / "vertices" / "carriers" / "lumen.csv", "city,state", "Reston,VA")


def _one_csp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down region files for the aws provider only under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(
        tmp_path / "vertices" / "csps" / "aws" / "east.csv", "city,state", "Reston,VA")


def _one_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Lay down one tenant config *body* and its input files under temp roots."""
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(seed, "ETC", tmp_path / "etc")
    _write_csv(tmp_path / "regions" / "aws.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "locations" / "f35.csv", "city,state", "Luke,AZ")
    _write_csv(tmp_path / "offnet" / "off.csv", "city,state", "Edge,TX")
    (tmp_path / "etc").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc" / "f_35.yml").write_text(body, encoding="utf-8")


def test_slug_replaces_underscores_with_hyphens() -> None:
    """_slug turns underscores into hyphens."""
    assert _slug("f_35_redundant") == "f-35-redundant"


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
    assert len(_mapping_rows({"east": ["a.csv"], "west": ["b.csv"]})) == 2


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
    assert "east" not in _mapping_rows({"east": "a.csv"})[0]


def test_carrier_names_returns_sorted_stems(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_names returns the CSV stems under data/edges, sorted."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "edges" / "lumen.csv", "a_city,z_city", "X,Y")
    _write_csv(tmp_path / "edges" / "cogent.csv", "a_city,z_city", "X,Y")
    assert _carrier_names() == ["cogent", "lumen"]


def test_carrier_names_ignores_non_csv_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_carrier_names ignores files that are not CSVs."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "edges" / "lumen.csv", "a_city,z_city", "X,Y")
    (tmp_path / "edges" / "notes.txt").write_text("x", encoding="utf-8")
    assert _carrier_names() == ["lumen"]


def test_put_uses_the_put_method(urlopen_recorder: UrlopenRecorder) -> None:
    """_put issues an HTTP PUT."""
    _put("http://api", "carriers/lumen/vertices", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].method == "PUT"


def test_put_targets_the_api_path(urlopen_recorder: UrlopenRecorder) -> None:
    """_put targets the api base joined with the resource path."""
    _put("http://api", "carriers/lumen/vertices", [])
    assert urlopen_recorder.requests[0].full_url == "http://api/carriers/lumen/vertices"


def test_put_encodes_the_json_body(urlopen_recorder: UrlopenRecorder) -> None:
    """_put sends the body as encoded JSON."""
    _put("http://api", "carriers/lumen/vertices", [{"city": "Reston"}])
    assert urlopen_recorder.requests[0].data == b'[{"city": "Reston"}]'


def test_put_sets_the_json_content_type(urlopen_recorder: UrlopenRecorder) -> None:
    """_put sets a JSON content-type header."""
    _put("http://api", "carriers/lumen/vertices", [])
    assert urlopen_recorder.requests[0].get_header("Content-type") == "application/json"


def test_put_prints_the_response_status(
        urlopen_recorder: UrlopenRecorder, capsys: pytest.CaptureFixture[str]) -> None:
    """_put prints the response status."""
    _put("http://api", "carriers/lumen/vertices", [])
    assert "-> 200" in capsys.readouterr().out


def test_push_carriers_puts_the_vertices_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier vertices."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/vertices" in [call[1] for call in put_recorder.calls]


def test_push_carriers_puts_the_edges_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier edges."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/edges" in [call[1] for call in put_recorder.calls]


def test_push_csps_pushes_provider_regions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_csps PUTs the combined regions for a provider that has files."""
    _one_csp(tmp_path, monkeypatch)
    push_csps("http://api")
    assert "csps/aws/vertices" in [call[1] for call in put_recorder.calls]


def test_push_csps_skips_providers_without_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_csps does not PUT for providers that have no region files."""
    _one_csp(tmp_path, monkeypatch)
    push_csps("http://api")
    assert "csps/azure/vertices" not in [call[1] for call in put_recorder.calls]


def test_push_tenants_puts_the_label_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants PUTs the tenant label."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    push_tenants("http://api")
    assert "tenants/f-35/label" in [call[1] for call in put_recorder.calls]


def test_push_tenants_reads_off_net_when_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends the off-net rows when an off_net file is given."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML)
    push_tenants("http://api")
    bodies = {call[1]: call[2] for call in put_recorder.calls}
    assert bodies["tenants/f-35/off-net"] == [{"city": "Edge", "state": "TX"}]


def test_push_tenants_uses_empty_off_net_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends an empty off-net list when no off_net is given."""
    _one_tenant(tmp_path, monkeypatch, _TENANT_YML.replace(
        "  off_net: offnet/off.csv\n", ""))
    push_tenants("http://api")
    bodies = {call[1]: call[2] for call in put_recorder.calls}
    assert bodies["tenants/f-35/off-net"] == []


def test_push_tenants_skips_empty_config_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants skips a tenant file that has no content."""
    _one_tenant(tmp_path, monkeypatch, "\n")
    push_tenants("http://api")
    assert put_recorder.calls == []


def _run_main(
        monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[tuple[str, str]]:
    """Run main() with stubbed push_* and *argv*; return the (name, api) calls."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(seed.sys, "argv", argv)
    monkeypatch.setattr(seed, "push_carriers", lambda api: calls.append(("carriers", api)))
    monkeypatch.setattr(seed, "push_csps", lambda api: calls.append(("csps", api)))
    monkeypatch.setattr(seed, "push_tenants", lambda api: calls.append(("tenants", api)))
    main()
    return calls


def test_main_defaults_to_the_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """main targets the default public API when given no argument."""
    assert _run_main(monkeypatch, ["seed"])[0] == ("carriers", seed.DEFAULT_API)


def test_main_uses_the_cli_argument_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """main targets the API URL passed on the command line."""
    assert _run_main(monkeypatch, ["seed", "http://custom"])[0][1] == "http://custom"


def test_main_seeds_carriers_then_csps_then_tenants(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """main seeds carriers, then CSPs, then tenants, in order."""
    assert [name for name, _ in _run_main(monkeypatch, ["seed"])] == [
        "carriers", "csps", "tenants"]
