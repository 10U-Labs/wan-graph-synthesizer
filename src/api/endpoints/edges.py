"""Endpoint serving a design's drawable edges: access, physical, and routed paths."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.context import payload_for

router = APIRouter()


@router.get("/api/wan-maps/{wan_map_id}/edges")
def get_edges(wan_map_id: str, request: Request) -> dict[str, Any]:
    """Return the access edges, physical carrier edges, and routed path uses."""
    payload = payload_for(request, wan_map_id)
    return {key: payload[key] for key in ("access_edges", "physical_edges", "path_uses")}
