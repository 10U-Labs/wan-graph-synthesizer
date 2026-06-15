#!/usr/bin/env python3
"""Entry point for the three-tier WAN designer CLI.

The operator role pins for the canonical design are expressed as explicit CLI
flags (not hidden constants): Salt Lake City and Ashburn are co-located
core+aggregation facilities, Atlanta anchors the southeast as a core, Herndon,
Portland, San Luis Obispo, Phoenix, New York, and Newark are aggregations, and
Ogden is barred from every selected role.

The two Long Island demand intents (Brookhaven and Shirley, NY) are not Lumen
PoPs in the mapbook, so they are mapped to the two nearest existing PoPs:
Brookhaven to New York, NY and Shirley to Newark, NJ.
"""

from __future__ import annotations

from wan_designer.cli import main

FORCED_DESIGN_ARGS = [
    "--force-core", "Salt Lake City, UT", "--force-aggregation", "Salt Lake City, UT",
    "--force-core", "Atlanta, GA",
    "--force-core", "Ashburn, VA", "--force-aggregation", "Ashburn, VA",
    "--force-aggregation", "Herndon, VA",
    "--force-aggregation", "Portland, OR",
    "--force-aggregation", "San Luis Obispo, CA",
    "--force-aggregation", "Phoenix, AZ",
    "--force-aggregation", "New York, NY",
    "--force-aggregation", "Newark, NJ",
    "--exclude", "Ogden, UT",
]

if __name__ == "__main__":
    raise SystemExit(main(FORCED_DESIGN_ARGS))
