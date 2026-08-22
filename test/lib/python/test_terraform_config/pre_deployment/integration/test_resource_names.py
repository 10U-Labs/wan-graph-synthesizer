from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names

PRODUCT = "wan-synthesizer"
ROUTING_MAIN = REPO_ROOT / "src" / "api" / "common" / "routing" / "main.tf"
API = REPO_ROOT / "src" / "api"

_ROLE_NAME = re.compile(r'^\s*(?:role_)?name\s*=\s*"(wan-[a-z-]+)"', re.M)
_INTEGRATION = re.compile(r"local\.integration\.(\w+)")


def _declared_resource_names() -> set[str]:
    return {
        match.group(1)
        for path in sorted(API.rglob("*.tf"))
        for match in _ROLE_NAME.finditer(path.read_text(encoding="utf-8"))
    }


def _named_after_the_product(name: str) -> bool:
    return name == PRODUCT or name.startswith(f"{PRODUCT}-")


def test_every_handler_function_is_named_after_the_repository() -> None:
    names = set(lambda_handler_names().values())
    assert {name for name in names if not _named_after_the_product(name)} == set()


def test_every_resource_the_stacks_declare_is_named_after_the_repository() -> None:
    declared = _declared_resource_names()
    assert {name for name in declared if not _named_after_the_product(name)} == set()


def test_every_route_integration_names_a_declared_handler() -> None:
    referenced = set(_INTEGRATION.findall(ROUTING_MAIN.read_text(encoding="utf-8")))
    assert referenced == set(lambda_handler_names())
