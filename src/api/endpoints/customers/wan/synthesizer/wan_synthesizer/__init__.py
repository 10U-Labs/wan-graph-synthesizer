"""The three-tier WAN design engine, run by the synthesizer endpoint.

Takes a JSON-loaded carrier graph plus a customer's demand and produces a
validated three-tier (core / aggregation / access) design. The Fargate synthesizer
entrypoint composes the submodules directly (``dual_home`` -> ``apply_role_overrides``
-> ``synthesize_three_tier_design`` -> ``finalize``); this package exposes no
re-exports. It reads no raw files -- the inputs script feeds it JSON via the
:mod:`wan_graph` interchange.
"""

from __future__ import annotations
