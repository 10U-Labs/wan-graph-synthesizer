"""Shared endpoint helper: resolve a request to its design payload.

Centralizing the app-state lookup and the unknown-config translation keeps each
atomic endpoint a one-liner and avoids duplicating the 404 handling.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from wan_designer.service import design_for_wan_map


def payload_for(request: Request, wan_map_id: str) -> dict[str, Any]:
    """Return the design payload for ``wan_map_id``, raising 404 if it is unknown."""
    try:
        return design_for_wan_map(
            request.app.state.config_dir, wan_map_id, request.app.state.cache
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown wan map: {wan_map_id}") from exc
