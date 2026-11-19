from __future__ import annotations

from custom_components.energy_facts.coordinator import _sync_marker


def test_marker_stops_at_first_unsynced_hour():
    recs = [
        {"timestamp": "2026-11-01T00:00:00", "synced": True},
        {"timestamp": "2026-11-01T01:00:00", "synced": False},
        {"timestamp": "2026-11-01T02:00:00", "synced": True},
    ]
    assert _sync_marker(recs) == "2026-11-01T01:00:00"


def test_marker_is_latest_when_all_synced():
    recs = [
        {"timestamp": "2026-11-01T00:00:00", "synced": True},
        {"timestamp": "2026-11-01T02:00:00", "synced": True},
    ]
    assert _sync_marker(recs) == "2026-11-01T02:00:00"
