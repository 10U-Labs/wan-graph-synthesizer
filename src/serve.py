#!/usr/bin/env python3
"""Self-hosted launcher for the WAN Graph Designer web app.

Serves the REST API and the Leaflet frontend from one process. Designs are
computed on demand from the configs in ``etc/`` (Joint, F-35), so no managed
service is required -- run it locally and open the printed URL.
"""

from __future__ import annotations

from pathlib import Path

import uvicorn

from api.app import build_app

HOST = "0.0.0.0"
PORT = 8000

if __name__ == "__main__":
    uvicorn.run(build_app(Path("etc"), Path("src/www")), host=HOST, port=PORT)
