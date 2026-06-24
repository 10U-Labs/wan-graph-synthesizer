"""Layer 1 (image): the reconcile job landed the synthesizer image in ECR.

The wan_post reconcile builds and pushes the synthesizer Docker image to the
``wan-graph-synthesizer`` ECR repo (the repo the wan stack declares) tagged
``latest``. This confirms an image carrying that tag actually exists.
"""
from __future__ import annotations

from typing import Any


def test_latest_image_is_present(ecr_client: Any) -> None:
    """The synthesizer repo holds an image tagged ``latest``."""
    response = ecr_client.describe_images(
        repositoryName="wan-graph-synthesizer",
        imageIds=[{"imageTag": "latest"}],
    )
    assert response["imageDetails"]
