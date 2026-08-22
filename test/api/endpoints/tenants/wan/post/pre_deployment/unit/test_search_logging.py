from __future__ import annotations

import pytest

import fixtures
from synthesizer.synthesize import synthesize_two_tier


def test_backbone_scan_logs_a_progress_heartbeat(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("synthesizer.synthesize._SEARCH_LOG_INTERVAL", 1)
    with caplog.at_level("INFO"):
        synthesize_two_tier(
            fixtures.ring_sites(), fixtures.ring_fiber_segments(), fixtures.ring_params()
        )
    assert any("scanned" in record.getMessage() for record in caplog.records)
