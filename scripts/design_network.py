#!/usr/bin/env python3
"""Entry point for the three-tier WAN designer's canonical design.

All operator choices -- the input files, the role pins (forced cores and
aggregations), the exclusions, and the algorithm dials -- live in
``etc/joint.yml`` rather than in this file, so changing the design no longer
means editing source. This script just runs the designer against that config;
the CLI flags in ``wan_designer.cli`` still override it for ad-hoc runs.
"""

from __future__ import annotations

from wan_designer.cli import main

CONFIG_ARGS = ["--config", "etc/joint.yml"]

if __name__ == "__main__":
    raise SystemExit(main(CONFIG_ARGS))
