from __future__ import annotations

import re
from typing import Any

from repo_utils import REPO_ROOT
from test_terraform_config import STATE_BUCKET

PREFIX = "wan-synthesizer/"
SRC = REPO_ROOT / "src"
STACKS = SRC / "api"

_KEY = re.compile(r'^\s*key\s*=\s*"([^"]+)"', re.M)


def _declared_keys() -> dict[str, str]:
    keys = {}
    for backend in sorted(SRC.rglob("backend.tf")):
        match = _KEY.search(backend.read_text(encoding="utf-8"))
        if match is not None:
            keys[str(backend.parent.relative_to(STACKS))] = match.group(1)
    return keys


def _read_keys() -> set[str]:
    return {
        match.group(1)
        for path in sorted(SRC.rglob("*.tf"))
        if path.name != "backend.tf"
        for match in _KEY.finditer(path.read_text(encoding="utf-8"))
    }


def test_every_stack_files_its_state_under_its_own_path() -> None:
    expected = {
        stack: f"{PREFIX}{stack}/terraform.tfstate" for stack in _declared_keys()
    }
    assert _declared_keys() == expected


def test_every_remote_state_read_names_the_repository_prefix() -> None:
    assert {key for key in _read_keys() if not key.startswith(PREFIX)} == set()


def test_every_remote_state_read_names_a_key_some_stack_writes() -> None:
    assert _read_keys() - set(_declared_keys().values()) == set()


def _stored_keys(s3_client: Any) -> set[str]:
    pages = s3_client.get_paginator("list_objects_v2").paginate(
        Bucket=STATE_BUCKET, Prefix=PREFIX
    )
    return {
        stored["Key"]
        for page in pages
        for stored in page.get("Contents", [])
        if not stored["Key"].endswith(".tflock")
    }


def test_every_stored_state_object_is_a_stack_that_still_exists(s3_client: Any) -> None:
    assert _stored_keys(s3_client) - set(_declared_keys().values()) == set()
