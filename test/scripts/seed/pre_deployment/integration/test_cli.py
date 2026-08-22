from __future__ import annotations

import os
import subprocess
import sys

from repo_utils import REPO_ROOT
from test_http_doubles import StubApi


def _run_seed(url: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([
            str(REPO_ROOT / "scripts"),
            str(REPO_ROOT / "lib" / "python"),
            str(REPO_ROOT),
        ]),
    }
    return subprocess.run(
        [sys.executable, "-c", "import seed; seed.main()", url],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, check=False,
    )


def test_seed_cli_exits_zero_against_the_stub(stub_api: StubApi) -> None:
    assert _run_seed(stub_api.url).returncode == 0


def test_seed_cli_writes_carrier_pops(stub_api: StubApi) -> None:
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any("/carriers/" in path and path.endswith("/pops") for path in paths)


def test_seed_cli_writes_a_tenant_label(stub_api: StubApi) -> None:
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any(path.endswith("/label") for path in paths)


def test_seed_cli_writes_the_backbone_number_of_diverse_paths(stub_api: StubApi) -> None:
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any(path.endswith("/backbone-number-of-diverse-paths") for path in paths)


def test_seed_cli_fails_when_the_api_rejects_writes() -> None:
    with StubApi(status=500) as api:
        result = _run_seed(api.url)
    assert result.returncode != 0
