"""Endpoint listing the selectable WAN maps (e.g. Joint, F-35)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from wan_designer.service import available_wan_maps

router = APIRouter()


@router.get("/api/wan-maps")
def list_wan_maps(request: Request) -> list[dict[str, str]]:
    """List each available WAN map as an ``{id, label}`` entry for the UI dropdown."""
    return available_wan_maps(request.app.state.config_dir)
