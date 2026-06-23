"""The core-set scan emits a progress heartbeat so a long search is observable."""

from __future__ import annotations

import pytest

import fixtures
from wan_synthesizer.synthesize import synthesize_three_tier_design


def test_core_scan_logs_a_progress_heartbeat(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """With a small interval, scanning core sets logs progress instead of going silent."""
    monkeypatch.setattr("wan_synthesizer.synthesize._SEARCH_LOG_INTERVAL", 1)
    with caplog.at_level("INFO"):
        synthesize_three_tier_design(
            fixtures.ring_vertices(), fixtures.ring_physical_edges(), fixtures.ring_params()
        )
    assert any("scanned" in record.getMessage() for record in caplog.records)
