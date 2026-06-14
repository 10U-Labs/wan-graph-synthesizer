#!/usr/bin/env python3
"""Entry point for the three-tier WAN designer CLI.

The operator role pins for the canonical design are expressed as explicit CLI
flags (not hidden constants): Ashburn and Salt Lake City are co-located
core+aggregation facilities, El Paso anchors the southwest as a core, Herndon is
an aggregation, and Ogden is barred from every selected role.
"""

from __future__ import annotations

from wan_designer.cli import main

FORCED_DESIGN_ARGS = [
    "--force-core", "Salt Lake City, UT", "--force-aggregation", "Salt Lake City, UT",
    "--force-core", "Ashburn, VA", "--force-aggregation", "Ashburn, VA",
    "--force-core", "El Paso, TX",
    "--force-aggregation", "Herndon, VA",
    "--exclude", "Ogden, UT",
]

if __name__ == "__main__":
    raise SystemExit(main(FORCED_DESIGN_ARGS))
