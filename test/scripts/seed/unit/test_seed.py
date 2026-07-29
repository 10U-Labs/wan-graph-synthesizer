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
    _carrier_names,
    _data_center_providers,
    _degree_doc,
    _delete,
    _get,
    _mapping_rows,
    _post,
    _put,
    _rows,
    _slug,
    build_data_centers,
    build_substrate,
    build_tenants,
    main,
    prune_tenants,
    push_carriers,
    push_data_centers,
    push_providers,
    push_tenants,
)

_TENANT_YML = """\
access:
  homing_degree: 1
backbone:
  mesh_degree: 2
backbone_node_count:
  max: 3
  min: 3
inputs:
  locations:
    F-35: locations/f35.csv
  off_net: offnet/off.csv
  providers:
    regions: regions/providers.csv
label: F-35
promote_high_degree_convergences_to_backbone_nodes: false
restrict_backbone_to_data_centers: true
settings:
  compass_sector_count: 4
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


def _one_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down the single provider regions file under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(
        tmp_path / "vertices" / "providers" / "providers.csv", "city,state", "Reston,VA")


def _one_data_center(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay down one colocation provider's facilities under a temp DATA dir."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(
        tmp_path / "vertices" / "data-centers" / "vision_net.csv", "city,state", "Helena,MT")


def _one_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Lay down one tenant config *body* and its input files under temp roots."""
    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(seed, "ETC", tmp_path / "etc")
    _write_csv(tmp_path / "regions" / "providers.csv", "city,state", "Reston,VA")
    _write_csv(tmp_path / "locations" / "f35.csv", "city,state", "Luke,AZ")
    _write_csv(tmp_path / "offnet" / "off.csv", "city,state", "Edge,TX")
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


@pytest.mark.usefixtures("urlopen_recorder")
def test_put_prints_the_response_status(capsys: pytest.CaptureFixture[str]) -> None:
    """_put prints the response status."""
    _put("http://api", "carriers/lumen/vertices", [])
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


def test_push_carriers_puts_the_vertices_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier vertices."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/vertices" in put_recorder.nth(1)


def test_push_carriers_puts_the_edges_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_carriers PUTs the carrier edges."""
    _one_carrier(tmp_path, monkeypatch)
    push_carriers("http://api")
    assert "carriers/lumen/edges" in put_recorder.nth(1)


def test_push_providers_pushes_regions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_providers PUTs the combined provider regions."""
    _one_provider(tmp_path, monkeypatch)
    push_providers("http://api")
    assert "providers/vertices" in put_recorder.nth(1)


def test_data_center_providers_returns_sorted_stems(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_data_center_providers returns the CSV stems under data-centers, sorted."""
    monkeypatch.setattr(seed, "DATA", tmp_path)
    _write_csv(tmp_path / "vertices" / "data-centers" / "lunavi.csv", "city,state", "X,Y")
    _write_csv(tmp_path / "vertices" / "data-centers" / "equinix.csv", "city,state", "X,Y")
    assert _data_center_providers() == ["equinix", "lunavi"]


def test_push_data_centers_puts_the_slugged_vertices_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_data_centers PUTs a provider's facilities under its slugged id."""
    _one_data_center(tmp_path, monkeypatch)
    push_data_centers("http://api")
    assert "data-centers/vision-net/vertices" in put_recorder.nth(1)


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


def test_push_tenants_puts_the_backbone_mesh_degree_resource(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants reads the mesh degree from the backbone block, not a root key."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/backbone-mesh-degree"] == {"degree": 2}


def test_push_tenants_puts_the_settings_document(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends the tenant's settings block as its own document."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/settings"] == {"compass_sector_count": 4}


def test_push_tenants_reads_off_net_when_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends the off-net rows when an off_net file is given."""
    bodies = _pushed_bodies(tmp_path, monkeypatch, put_recorder)
    assert bodies["tenants/f-35/off-net"] == [{"city": "Edge", "state": "TX"}]


def test_push_tenants_uses_empty_off_net_when_absent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        put_recorder: CallRecorder) -> None:
    """push_tenants sends an empty off-net list when no off_net is given."""
    bodies = _pushed_bodies(
        tmp_path, monkeypatch, put_recorder,
        _TENANT_YML.replace("  off_net: offnet/off.csv\n", ""))
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


def test_build_substrate_posts_the_merge(post_recorder: CallRecorder) -> None:
    """build_substrate POSTs the carrier merge."""
    build_substrate("http://api")
    assert post_recorder.calls == [("http://api", "carriers/merge")]


def test_build_data_centers_posts_the_merge(post_recorder: CallRecorder) -> None:
    """build_data_centers POSTs the data-centers merge."""
    build_data_centers("http://api")
    assert post_recorder.calls == [("http://api", "data-centers/merge")]


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
    monkeypatch.setattr(seed, "build_substrate", lambda api: calls.append(("merge", api)))
    monkeypatch.setattr(seed, "push_providers", lambda api: calls.append(("providers", api)))
    monkeypatch.setattr(
        seed, "push_data_centers", lambda api: calls.append(("data-centers", api)))
    monkeypatch.setattr(
        seed, "build_data_centers", lambda api: calls.append(("dc-merge", api)))
    monkeypatch.setattr(seed, "push_tenants", _push_tenants)
    monkeypatch.setattr(
        seed, "prune_tenants",
        lambda _api, tenants: calls.append(("prune", ",".join(tenants))))
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
    """main seeds carriers, substrate, providers, data-centers (+union), tenants, then builds."""
    assert [name for name, _ in _run_main(monkeypatch, ["seed"])] == [
        "carriers", "merge", "providers", "data-centers", "dc-merge", "tenants",
        "prune", "build"]


def test_main_prunes_against_the_pushed_tenant_ids(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """main hands the ids it just pushed to the prune step, as the roster to keep."""
    assert ("prune", "t") in _run_main(monkeypatch, ["seed"])
