"""Contract: every stack files its state at the address its own path names.

OpenTofu keeps one JSON object per stack recording every AWS resource that stack made and
the id AWS gave it. That object is how the next apply knows the API Gateway, the bucket
and the Lambdas already exist; an apply that cannot find it believes it is starting from
nothing and tries to create all of them again.

What a wrong address costs is silence. A ``terraform_remote_state`` pointed at a key
nothing writes is not an error -- it is an empty set of outputs, so the stack reading it
loses the bucket name or the gateway id and carries on. These tests hold the ten-odd
declarations against each other so a key that moves in one place and not another fails
here instead of on the next apply.

They live in this module because its subtree runs in the ``test-repo-libraries`` job of
every workflow, so a stack filed at the wrong address fails every workflow on the push
that files it rather than only its own.
"""

from __future__ import annotations

import re

from repo_utils import REPO_ROOT

PREFIX = "wan-synthesizer/"
SRC = REPO_ROOT / "src"
STACKS = SRC / "api"

_KEY = re.compile(r'^\s*key\s*=\s*"([^"]+)"', re.M)


def _declared_keys() -> dict[str, str]:
    """The state key each ``backend.tf`` under ``src/`` declares, by its stack's path."""
    keys = {}
    for backend in sorted(SRC.rglob("backend.tf")):
        match = _KEY.search(backend.read_text(encoding="utf-8"))
        if match is not None:
            keys[str(backend.parent.relative_to(STACKS))] = match.group(1)
    return keys


def _read_keys() -> set[str]:
    """Every state key a ``terraform_remote_state`` block anywhere under ``src/`` names."""
    return {
        match.group(1)
        for path in sorted(SRC.rglob("*.tf"))
        if path.name != "backend.tf"
        for match in _KEY.finditer(path.read_text(encoding="utf-8"))
    }


def test_every_stack_files_its_state_under_its_own_path() -> None:
    """Each stack's key is the prefix, its path under ``src/api/``, and the state file.

    Asserted as one mapping rather than stack by stack, so a stack filed under another
    stack's path fails as loudly as one filed under a stale prefix.
    """
    expected = {
        stack: f"{PREFIX}{stack}/terraform.tfstate" for stack in _declared_keys()
    }
    assert _declared_keys() == expected


def test_every_remote_state_read_names_the_repository_prefix() -> None:
    """Every key read across stacks begins with this repository's state prefix.

    The eight existing substring assertions in the endpoints' own contract tiers check
    which stack is being read and start after the prefix, so they pass whatever it is --
    including a prefix naming a different product.
    """
    assert {key for key in _read_keys() if not key.startswith(PREFIX)} == set()


def test_every_remote_state_read_names_a_key_some_stack_writes() -> None:
    """Every key read across stacks is one a ``backend.tf`` declares.

    A read pointed at a key nothing writes returns empty outputs rather than failing,
    which is the silence this file exists to break.
    """
    assert _read_keys() - set(_declared_keys().values()) == set()
