"""Integration tests: the seed CLI as a subprocess against a stub API.

These invoke the real ``python -m seed`` entrypoint as its own process over the
repository's real inputs, with the API replaced by a localhost stub that records
every request. Nothing leaves the machine and no live resource is touched.

That last sentence is why this sits in the pre-deployment integration tier and
not in end to end, where it used to be filed. It is several real units against
each other with nothing deployed, which
docs/tenets/tests/PRE_DEPLOYMENT_INTEGRATION_TESTS.md places here, and it never
stands in for the question docs/tenets/tests/E2E_TESTS.md asks: what a caller
receives from the deployed program. test_delivered_syntheses.py under
../../post_deployment/e2e/ is the tier that asks it (GitHub issue #49).
"""

from __future__ import annotations

import os
import subprocess
import sys

from repo_utils import REPO_ROOT
from test_http_doubles import StubApi


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


def test_seed_cli_writes_the_backbone_number_of_diverse_paths(stub_api: StubApi) -> None:
    """The seed CLI writes each tenant's diverse path count to its own resource.

    The resource name is the one place the rename off the graph-theory word is observable
    from outside the process, so this tier is where it is held: the tenant configs and the
    reader of them could both be renamed together and pass every other test unchanged.
    """
    _run_seed(stub_api.url)
    paths = [path for _method, path, _body in stub_api.records]
    assert any(path.endswith("/backbone-number-of-diverse-paths") for path in paths)


def test_seed_cli_fails_when_the_api_rejects_writes() -> None:
    """The seed CLI exits non-zero when the API returns an error status."""
    with StubApi(status=500) as api:
        result = _run_seed(api.url)
    assert result.returncode != 0
