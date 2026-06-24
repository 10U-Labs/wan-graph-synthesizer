"""Unit tests for the seed push half: seeding the API from git-authored inputs.

The network and filesystem are mocked -- ``urlopen`` is replaced so no real PUTs
leave the process, and the data/ + etc/ roots are redirected at ``tmp_path``. The
private helpers (``_put``, ``_slug``, ``_carrier_names``, ``_rows``, ``_mapping_rows``,
``_degree_doc``) are exercised through the public ``push_*`` / ``main`` entry points.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import seed

_POP_CSV = "Municipality,State,Latitude,Longitude\nDenver,CO,39.7,-104.9\nOmaha,NE,41.2,-96.0\n"
_EDGE_CSV = "A_Municipality,A_State,Z_Municipality,Z_State\nDenver,CO,Omaha,NE\n"
_REGION_CSV = "Name,Municipality,State,Latitude,Longitude\nus-east-1,Ashburn,VA,38.0,-79.0\n"
_OFFNET_CSV = "Municipality,State,Latitude,Longitude\nDulles,VA,39.0,-77.4\n"
_LOC_CSV = "Name,Municipality,State,Latitude,Longitude\nHill AFB,Layton,UT,41.1,-111.9\n"

_TENANT_YML_WITH_OFFNET = """\
inputs:
  locations:
    F-35: data/loc.csv
  csps:
    AWS:
      - data/region.csv
  off_net: data/offnet.csv
core_mesh_degree: 3
aggregation_homing_degree: 2
access_homing_degree: 2
"""

_TENANT_YML_MINIMAL = """\
core_mesh_degree: 3
aggregation_homing_degree: 2
access_homing_degree: 2
"""

_TENANT_YML_BAD_OFFNET = """\
inputs:
  off_net: data/missing.csv
core_mesh_degree: 3
aggregation_homing_degree: 2
access_homing_degree: 2
"""


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Patch urlopen to record each request and return a dummy response."""
    requests: list[Any] = []

    def _fake_urlopen(request: Any, **_kwargs: Any) -> Any:
        requests.append(request)
        return MagicMock()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return requests


def _noop(_api: str) -> None:
    """Stand in for a push step that should do nothing."""


def _setup_carriers(root: Path) -> None:
    """Write one carrier's vertices and fiber edges under a data root."""
    carriers = root / "vertices" / "carriers"
    carriers.mkdir(parents=True)
    (carriers / "lumen.csv").write_text(_POP_CSV, encoding="utf-8")
    edges = root / "edges"
    edges.mkdir(parents=True)
    (edges / "lumen.csv").write_text(_EDGE_CSV, encoding="utf-8")


def _setup_csps(root: Path) -> None:
    """Write regions for aws only (azure and oci stay absent)."""
    aws = root / "vertices" / "csps" / "aws"
    aws.mkdir(parents=True)
    (aws / "regions.csv").write_text(_REGION_CSV, encoding="utf-8")


def _setup_tenant(root: Path, name: str, yaml_text: str) -> None:
    """Write a tenant config plus the CSVs an off-net config references."""
    etc = root / "etc"
    etc.mkdir(exist_ok=True)
    (etc / f"{name}.yml").write_text(yaml_text, encoding="utf-8")
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / "loc.csv").write_text(_LOC_CSV, encoding="utf-8")
    (data / "region.csv").write_text(_REGION_CSV, encoding="utf-8")
    (data / "offnet.csv").write_text(_OFFNET_CSV, encoding="utf-8")


def _run_push_tenants(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Redirect the etc/ + repo roots at ``root`` and run push_tenants."""
    requests = _capture_requests(monkeypatch)
    monkeypatch.setattr(seed,"ETC", root / "etc")
    monkeypatch.setattr(seed,"REPO_ROOT", root)
    seed.push_tenants("http://api")
    return requests


def _stub_pushes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the three push steps; return the list push_carriers records into."""
    seen: list[str] = []
    monkeypatch.setattr(seed,"push_carriers", seen.append)
    monkeypatch.setattr(seed,"push_csps", _noop)
    monkeypatch.setattr(seed,"push_tenants", _noop)
    return seen


def test_push_carriers_puts_vertices_then_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """push_carriers PUTs each carrier's vertices and then its fiber edges."""
    _setup_carriers(tmp_path)
    requests = _capture_requests(monkeypatch)
    monkeypatch.setattr(seed,"DATA", tmp_path)
    seed.push_carriers("http://api")
    assert [r.full_url for r in requests] == [
        "http://api/carriers/lumen/vertices",
        "http://api/carriers/lumen/edges",
    ]


def test_push_csps_skips_providers_without_region_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """push_csps PUTs providers that have region files and skips the rest."""
    _setup_csps(tmp_path)
    requests = _capture_requests(monkeypatch)
    monkeypatch.setattr(seed,"DATA", tmp_path)
    seed.push_csps("http://api")
    assert [r.full_url for r in requests] == ["http://api/csps/aws/vertices"]


def test_push_tenants_puts_every_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant with locations, CSP regions, and off-net PUTs all 15 resources."""
    _setup_tenant(tmp_path, "f-35", _TENANT_YML_WITH_OFFNET)
    requests = _run_push_tenants(tmp_path, monkeypatch)
    assert len(requests) == 15


def test_push_tenants_handles_a_tenant_without_off_net(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant with no off-net config PUTs an empty off-net graph."""
    _setup_tenant(tmp_path, "plain", _TENANT_YML_MINIMAL)
    requests = _run_push_tenants(tmp_path, monkeypatch)
    off_net = next(r for r in requests if r.full_url.endswith("/off-net"))
    assert json.loads(off_net.data) == []


def test_push_tenants_rejects_a_missing_input_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config that points at an absent CSV is reported as an error."""
    _setup_tenant(tmp_path, "bad", _TENANT_YML_BAD_OFFNET)
    with pytest.raises(ValueError):
        _run_push_tenants(tmp_path, monkeypatch)


def test_main_defaults_to_the_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a CLI argument, main seeds against the default API base."""
    seen = _stub_pushes(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["seed.py"])
    seed.main()
    assert seen == [seed.DEFAULT_API]


def test_main_uses_the_cli_api_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CLI argument overrides the default API base."""
    seen = _stub_pushes(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["seed.py", "http://custom"])
    seed.main()
    assert seen == ["http://custom"]
