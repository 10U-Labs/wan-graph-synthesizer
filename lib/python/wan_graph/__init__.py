"""The WAN graph interchange: the data model and its JSON collections.

The shared contract between the inputs script (which writes these shapes as JSON)
and the optimizer endpoint (which reads them back): :mod:`wan_graph.model` holds the
vertex/edge dataclasses, :mod:`wan_graph.graph_collections` the JSON views. Import
the submodules directly; this package exposes no re-exports.
"""

from __future__ import annotations
