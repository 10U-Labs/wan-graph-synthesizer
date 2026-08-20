"""Contract: every AWS resource this product owns is named after the repository.

An operator in the AWS console reads the name AWS knows a resource by and nothing else,
so those names are the one place the repository's name is on show. They are also a
coupling: the routing stack builds each route's integration ARN out of the same
``lambda_handler_names`` the endpoint stacks create their functions with, and the two
stacks deploy from separate workflows that GitHub Actions orders nothing between.

What a half-finished rename costs is every route at once. A gateway whose integrations
name a function no stack has created yet answers HTTP 500 for as long as the window
lasts, and the tier that would notice -- the end-to-end one in ``seed.yml`` -- is not
started by a push that changes only ``lib/opentofu/common/outputs.tf``.

These run in the ``test-repo-libraries`` job of every workflow, so a rename left half
done fails all of them on the push that does it rather than one of them afterwards.
"""

from __future__ import annotations

import re

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names

PREFIX = "wan-synthesizer-"
ROUTING_MAIN = REPO_ROOT / "src" / "api" / "common" / "routing" / "main.tf"
ENDPOINTS = REPO_ROOT / "src" / "api" / "endpoints"

_ROLE_NAME = re.compile(r'^\s*(?:role_)?name\s*=\s*"(wan-[a-z-]+)"', re.M)
_INTEGRATION = re.compile(r"local\.integration\.(\w+)")


def _declared_role_names() -> set[str]:
    """Every IAM role name written out across the endpoint stacks."""
    return {
        match.group(1)
        for path in sorted(ENDPOINTS.rglob("*.tf"))
        for match in _ROLE_NAME.finditer(path.read_text(encoding="utf-8"))
    }


def test_every_handler_function_is_named_after_the_repository() -> None:
    """Every name in ``lambda_handler_names`` begins with the repository's prefix."""
    names = set(lambda_handler_names().values())
    assert {name for name in names if not name.startswith(PREFIX)} == set()


def test_every_role_the_endpoints_declare_is_named_after_the_repository() -> None:
    """Every IAM role and layer name the endpoint stacks write out carries the prefix."""
    declared = _declared_role_names()
    assert {name for name in declared if not name.startswith(PREFIX)} == set()


def test_every_route_integration_names_a_declared_handler() -> None:
    """The keys the routing stack builds integration ARNs from are exactly the declared ones.

    Stated in a comment at ``src/api/common/routing/main.tf`` and checked nowhere until
    now: an integration naming a handler nothing declares is a route to a function that
    does not exist, and a declared handler no route names is a Lambda nothing reaches.
    """
    referenced = set(_INTEGRATION.findall(ROUTING_MAIN.read_text(encoding="utf-8")))
    assert referenced == set(lambda_handler_names())
