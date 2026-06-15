"""Assemble the FastAPI app: the atomic design endpoints plus the static UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.endpoints import edges, summary, validation, vertices, wan_maps


def build_app(config_dir: Path, static_dir: Path) -> FastAPI:
    """Build the app serving designs for the configs in ``config_dir`` plus the UI.

    Designs are computed on demand and memoized in an app-scoped cache, so each
    atomic endpoint serves a slice of one shared computation per config.
    """
    app = FastAPI(title="WAN Graph Designer")
    app.state.config_dir = config_dir
    app.state.cache = {}
    for router in (
        wan_maps.router,
        vertices.router,
        edges.router,
        validation.router,
        summary.router,
    ):
        app.include_router(router)
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="www")
    return app
