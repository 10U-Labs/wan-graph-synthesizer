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

PRODUCT = "wan-synthesizer"
ROUTING_MAIN = REPO_ROOT / "src" / "api" / "common" / "routing" / "main.tf"
API = REPO_ROOT / "src" / "api"

_ROLE_NAME = re.compile(r'^\s*(?:role_)?name\s*=\s*"(wan-[a-z-]+)"', re.M)
_INTEGRATION = re.compile(r"local\.integration\.(\w+)")


def _declared_resource_names() -> set[str]:
    """Every resource name written out across the stacks under ``src/api``.

    The whole of ``src/api`` rather than its ``endpoints`` half, because a name is not only
    ever an endpoint's: the store's own prune handler holds the one role in the product
    that may delete from the bucket and is declared beside the bucket, and the API gateway
    the whole product answers on is declared in ``common/routing``.
    """
    return {
        match.group(1)
        for path in sorted(API.rglob("*.tf"))
        for match in _ROLE_NAME.finditer(path.read_text(encoding="utf-8"))
    }


def _named_after_the_product(name: str) -> bool:
    """Whether one resource name is the product's own name or is qualified out of it.

    The gateway is called ``wan-synthesizer`` and nothing else, because it is the product's
    one API rather than one of its parts; everything else adds a hyphen and says which part
    it is. Both read as named after the repository, and a name that merely starts with the
    same letters does not.
    """
    return name == PRODUCT or name.startswith(f"{PRODUCT}-")


def test_every_handler_function_is_named_after_the_repository() -> None:
    """Every name in ``lambda_handler_names`` is the product's name or qualified out of it."""
    names = set(lambda_handler_names().values())
    assert {name for name in names if not _named_after_the_product(name)} == set()


def test_every_resource_the_stacks_declare_is_named_after_the_repository() -> None:
    """Every name the stacks under src/api write out is the product's or qualified out of it."""
    declared = _declared_resource_names()
    assert {name for name in declared if not _named_after_the_product(name)} == set()


def test_every_route_integration_names_a_declared_handler() -> None:
    """The keys the routing stack builds integration ARNs from are exactly the declared ones.

    Stated in a comment at ``src/api/common/routing/main.tf`` and checked nowhere until
    now: an integration naming a handler nothing declares is a route to a function that
    does not exist, and a declared handler no route names is a Lambda nothing reaches.
    """
    referenced = set(_INTEGRATION.findall(ROUTING_MAIN.read_text(encoding="utf-8")))
    assert referenced == set(lambda_handler_names())
