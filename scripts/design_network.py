#!/usr/bin/env python3
"""Entry point for the three-tier WAN designer CLI.

The operator role pins for the canonical design are expressed as explicit CLI
flags (not hidden constants): Atlanta anchors the southeast and Philadelphia
anchors the northeast as cores, and McLean, Portland, San Luis Obispo, New York,
and Norfolk are aggregations.

The two Long Island demand intents (Brookhaven and Shirley, NY) are not Lumen
PoPs in the mapbook, so they are mapped to the two nearest existing PoPs:
Brookhaven to New York, NY and Shirley to Newark, NJ.
"""

from __future__ import annotations

from wan_designer.cli import main

FORCED_DESIGN_ARGS = [
    "--force-core", "Atlanta, GA",
    "--force-core", "Philadelphia, PA",
    "--force-aggregation", "McLean, VA",
    "--force-aggregation", "Portland, OR",
    "--force-aggregation", "San Luis Obispo, CA",
    "--force-aggregation", "New York, NY",
    "--force-aggregation", "Norfolk, VA",
]

if __name__ == "__main__":
    raise SystemExit(main(FORCED_DESIGN_ARGS))
