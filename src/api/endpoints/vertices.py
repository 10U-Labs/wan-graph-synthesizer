"""Endpoint serving a design's vertices with their tier roles and coordinates."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.context import payload_for

router = APIRouter()


@router.get("/api/wan-maps/{wan_map_id}/vertices")
def get_vertices(wan_map_id: str, request: Request) -> list[dict[str, Any]]:
    """Return every vertex with its tier role, kind, tenant, and coordinates."""
    return payload_for(request, wan_map_id)["vertices"]
