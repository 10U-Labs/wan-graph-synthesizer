"""End-to-end tests: the seed CLI as a subprocess against a stub API.

These invoke the real ``python -m seed`` entrypoint as its own process over the
repository's real inputs, with the API replaced by a localhost stub that records
every request. Nothing leaves the machine and no live resource is touched.
"""

from __future__ import annotations

import os
import subprocess
import sys

from http_test_doubles import StubApi
from repo_utils import REPO_ROOT


def _run_seed(url: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m seed <url>`` as a subprocess against a stub API."""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([
            str(REPO_ROOT / "scripts"),
            str(REPO_ROOT / "lib" / "python"),
            str(REPO_ROOT),
        ]),
    }
    return subprocess.run(
        [sys.executable, "-m", "seed", url],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, check=False,
    )


def test_seed_cli_exits_zero_against_the_stub(stub_api: StubApi) -> None:
    """The seed CLI exits 0 when the API accepts every write."""
    assert _run_seed(stub_api.url).returncode == 0


def test_seed_cli_writes_carrier_vertices(stub_api: StubApi) -> None:
    """The seed CLI writes carrier vertices to the API."""
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any("/carriers/" in path and path.endswith("/vertices") for path in paths)


def test_seed_cli_writes_a_tenant_label(stub_api: StubApi) -> None:
    """The seed CLI writes a tenant label to the API."""
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any(path.endswith("/label") for path in paths)


def test_seed_cli_fails_when_the_api_rejects_writes() -> None:
    """The seed CLI exits non-zero when the API returns an error status."""
    with StubApi(status=500) as api:
        result = _run_seed(api.url)
    assert result.returncode != 0
