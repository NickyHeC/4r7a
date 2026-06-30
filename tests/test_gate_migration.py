"""Tests for config/state.json gate key migration."""

from __future__ import annotations

import json

from company_brain.agents.gates import StateStore, migrate_gate_keys


def test_migrate_gate_keys_renames_handled_and_scanner_prefix(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "handled:granola_ingest": "2026-06-01",
                "handled:granola_miss_check": "2026-W23",
                "notion_task_scanner:last_scan:engineering": "2026-06-01T12:00:00+00:00",
                "linear_manager:last_poll": "2026-06-01T08:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
    )
    store = StateStore(path=path)
    counts = migrate_gate_keys(store=store)
    data = json.loads(path.read_text())

    assert counts == {"handled": 2, "state": 1}
    assert data["handled:ingest"] == "2026-06-01"
    assert data["handled:miss_check"] == "2026-W23"
    assert "handled:granola_ingest" not in data
    assert data["task_scanner:last_scan:engineering"] == "2026-06-01T12:00:00+00:00"
    assert "notion_task_scanner:last_scan:engineering" not in data
    assert data["linear_manager:last_poll"] == "2026-06-01T08:00:00+00:00"
