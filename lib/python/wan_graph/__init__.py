"""The WAN graph interchange: the shared types and the JSON wire format.

The thin contract shared by the inputs script (which writes these shapes as JSON)
and the optimizer (which reads them back): :mod:`wan_graph.model` holds the shared
vertex/edge dataclasses and geographic helpers, :mod:`wan_graph.codec` the input-graph
JSON codec. The optimizer's own design vocabulary lives in ``wan_designer.model``, not
here. Import the submodules directly; this package exposes no re-exports.
"""

from __future__ import annotations
