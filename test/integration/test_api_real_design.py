"""Integration test: a real config validates end-to-end through the REST API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import build_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_joint_design_validates_through_api() -> None:
    """The real Joint design reports a connected topology via the API."""
    client = TestClient(build_app(REPO_ROOT / "etc", REPO_ROOT / "src" / "www"))
    report = client.get("/api/wan-maps/joint/validation").json()
    assert report["connected"] is True
