from __future__ import annotations

import json
from typing import Any

from repo_utils import REPO_ROOT
from test_terraform_config import output_values

STORAGE_DIR = REPO_ROOT / "src" / "api" / "common" / "storage"


def test_outputs_declare_the_bucket_name_and_arn() -> None:
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert set(outputs) == {"bucket_name", "bucket_arn"}


def test_bucket_name_output_references_the_declared_store() -> None:
    outputs = output_values(STORAGE_DIR / "outputs.tf")
    assert "aws_s3_bucket.store" in str(outputs["bucket_name"])


def _tenant_collections_the_api_serves() -> set[str]:
    spec = json.loads((REPO_ROOT / "src" / "www" / "api" / "openapi.json").read_text("utf-8"))
    prefix = "/wan-synthesizer/tenants/{tenant}/"
    return {
        f"{route.removeprefix(prefix)}.json"
        for route, verbs in spec["paths"].items()
        if route.startswith(prefix) and "put" in verbs
    }


def test_the_prune_keeps_every_tenant_document_the_api_can_write(prune_handler: Any) -> None:
    assert _tenant_collections_the_api_serves() <= prune_handler.TENANT_FILES


def test_the_prune_keeps_no_tenant_document_the_api_cannot_write(prune_handler: Any) -> None:
    extra = set(prune_handler.TENANT_FILES) - _tenant_collections_the_api_serves()
    assert extra == {"wan.json", "wan-status.json"}
