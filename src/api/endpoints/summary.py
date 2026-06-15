"""Endpoint serving a design's tier summary: counts, miles, and chosen cores."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.context import payload_for

router = APIRouter()


@router.get("/api/wan-maps/{wan_map_id}/summary")
def get_summary(wan_map_id: str, request: Request) -> dict[str, Any]:
    """Return the tier counts, mileage totals, score, cores, and aggregations."""
    summary: dict[str, Any] = payload_for(request, wan_map_id)["summary"]
    return summary
