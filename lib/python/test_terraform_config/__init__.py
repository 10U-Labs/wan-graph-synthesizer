"""Parse shared OpenTofu configuration for tests and tooling.

This module is the single source of truth for configuration values that live
as literal ``output`` blocks in ``lib/opentofu/common/outputs.tf``. It parses
those blocks via the ``hcl2`` library so tests never hardcode an account id,
region, bucket, or Lambda function name.

Example usage::

    from test_terraform_config import common_outputs, TEST_AWS_REGION

    config = common_outputs()
    account = config["aws_account_id"]
    handlers = config["lambda_handler_names"]

    # For unit-test mock data (fake ARNs, URLs, etc.):
    mock_arn = f"arn:aws:sns:{TEST_AWS_REGION}:123456789012:test-topic"
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

from hcl2.api import load as hcl2_load

from repo_utils import REPO_ROOT

COMMON_OUTPUTS_FILE: Path = REPO_ROOT / "lib" / "opentofu" / "common" / "outputs.tf"


def load_tf(path: Path) -> dict[str, object]:
    """Load and parse an OpenTofu ``.tf`` file into a dict.

    Args:
        path: Path to the ``.tf`` file to parse.

    Returns:
        The parsed HCL document as a nested dict.
    """
    with open(path, encoding="utf-8") as handle:
        return cast("dict[str, object]", hcl2_load(handle))


def find_resource(
    tf_config: dict[str, object],
    resource_type: str,
    resource_name: str,
) -> dict[str, object] | None:
    """Locate a single resource block within a parsed ``.tf`` document.

    Args:
        tf_config: A document returned by :func:`load_tf`.
        resource_type: Terraform resource type (e.g. ``aws_s3_bucket``).
        resource_name: Terraform-local resource name (the second label).

    Returns:
        The resource body as a dict, or ``None`` if no such block exists.
    """
    resources = tf_config.get("resource", [])
    if not isinstance(resources, list):
        return None
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        by_name = resource.get(resource_type)
        if isinstance(by_name, dict) and resource_name in by_name:
            body = by_name[resource_name]
            if isinstance(body, dict):
                return cast("dict[str, object]", body)
    return None


def output_values(path: Path) -> dict[str, object]:
    """Return the literal value of every ``output`` block in a ``.tf`` file.

    Each ``output "name" { value = ... }`` block is reduced to its parsed
    literal value. String outputs become ``str`` and map outputs (such as
    ``lambda_handler_names``) become ``dict``.

    Args:
        path: Path to a ``.tf`` file declaring ``output`` blocks.

    Returns:
        A dict mapping each output name to its literal value.
    """
    document = load_tf(path)
    blocks = document.get("output", [])
    values: dict[str, object] = {}
    if not isinstance(blocks, list):
        return values
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for name, body in block.items():
            if isinstance(body, dict) and "value" in body:
                values[name] = body["value"]
    return values


def common_outputs() -> dict[str, object]:
    """Return the literal values of every output in ``common/outputs.tf``.

    Returns:
        A dict mapping each shared output name to its literal value.
    """
    return output_values(COMMON_OUTPUTS_FILE)


def lambda_handler_names() -> dict[str, str]:
    """Return the per-resource Lambda function names from common outputs.

    Returns:
        A dict mapping each REST resource key to its Lambda function name.
    """
    raw = common_outputs().get("lambda_handler_names", {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _string_output(name: str, fallback: str) -> str:
    """Return a string-valued common output, falling back if absent."""
    value = common_outputs().get(name, fallback)
    return value if isinstance(value, str) else fallback


# Single source of truth for the AWS region and state bucket, derived from the
# shared OpenTofu common module. Use TEST_AWS_REGION in unit tests for mock data
# (fake ARNs, URLs, etc.) instead of hardcoding region strings.
TEST_AWS_REGION: str = _string_output("aws_region", "us-east-2")
STATE_BUCKET: str = _string_output("state_bucket", "10ulabs-terraform-state-us-east-2")
