"""Endpoint serving a design's structural validation report."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.context import payload_for

router = APIRouter()


@router.get("/api/wan-maps/{wan_map_id}/validation")
def get_validation(wan_map_id: str, request: Request) -> dict[str, Any]:
    """Return the connectivity, dual-homing, and core-backbone validation report."""
    report: dict[str, Any] = payload_for(request, wan_map_id)["validation"]
    return report
