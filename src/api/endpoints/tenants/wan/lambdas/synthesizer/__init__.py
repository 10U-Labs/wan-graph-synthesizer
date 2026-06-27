"""The two-tier WAN design engine, run by the synthesizer worker Lambda.

Takes a JSON-loaded carrier graph plus a tenant's demand and produces a
validated two-tier (backbone / demand) design. The worker handler
(``synthesizer.handler``) composes the submodules directly (``dual_home`` ->
``apply_role_overrides`` -> ``synthesize_two_tier_design`` -> ``finalize``); this
package exposes no re-exports. It reads no raw files -- the handler loads the stored
JSON inputs into graph objects via :mod:`synthesizer.codec` first.
"""

from __future__ import annotations
