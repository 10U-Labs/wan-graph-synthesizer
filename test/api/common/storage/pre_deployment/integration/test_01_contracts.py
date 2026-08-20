"""Layer 1 (contracts): cross-file consistency within the storage stack.

These assert that the stack's published outputs match the resources it declares, and that
the prune endpoint's idea of what the store legitimately holds matches the routes
``src/www/api/openapi.json`` declares. No AWS calls.
"""
from __future__ import annotations

import json
from typing import Any

from repo_utils import REPO_ROOT
from test_terraform_config import output_values

STORAGE_DIR = REPO_ROOT / "src" / "api" / "common" / "storage"


def test_outputs_declare_the_bucket_name_and_arn() -> None:
    """The stack publishes exactly the store bucket's name and ARN."""
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert set(outputs) == {"bucket_name", "bucket_arn"}


def test_bucket_name_output_references_the_declared_store() -> None:
    """The ``bucket_name`` output is wired to the declared store resource."""
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert "aws_s3_bucket.store" in str(outputs["bucket_name"])


def _tenant_collections_the_api_serves() -> set[str]:
    """The tenant documents the API declares a PUT for, as stored file names.

    Read from ``src/www/api/openapi.json``, which is the one place a route exists: a
    collection an operator can write is a collection the store legitimately holds.
    """
    spec = json.loads((REPO_ROOT / "src" / "www" / "api" / "openapi.json").read_text("utf-8"))
    prefix = "/wan-synthesizer/tenants/{tenant}/"
    return {
        f"{route.removeprefix(prefix)}.json"
        for route, verbs in spec["paths"].items()
        if route.startswith(prefix) and "put" in verbs
    }


def test_the_prune_keeps_every_tenant_document_the_api_can_write(prune_handler: Any) -> None:
    """A collection an operator can PUT is one the prune must never take out.

    The prune decides what is current from its own list and the API decides what an operator
    may write from ``openapi.json``, and nothing else holds the two together. This is the
    direction that costs data: a collection dropped from the prune's list while its route
    still exists is deleted from the store on the next seed run.
    """
    assert _tenant_collections_the_api_serves() <= prune_handler.TENANT_FILES


def test_the_prune_keeps_no_tenant_document_the_api_cannot_write(prune_handler: Any) -> None:
    """The only names the prune protects beyond the routes are the two the build publishes.

    A name in the prune's list that no route writes and no build publishes is a collection
    that has been renamed away and is being protected by mistake, which is how a leftover
    survives a prune written to remove it.
    """
    extra = set(prune_handler.TENANT_FILES) - _tenant_collections_the_api_serves()
    assert extra == {"wan.json", "wan-status.json"}
