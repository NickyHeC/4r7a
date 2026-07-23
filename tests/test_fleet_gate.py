"""Fleet pause gate + redeploy cue."""

from __future__ import annotations

from pathlib import Path

import pytest

from company_brain.agents.base import SKIPPED, BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig, NotionConfig, WikiConfig
from company_brain.runtime import fleet_gate


def _cfg() -> AppConfig:
    return AppConfig(wiki=WikiConfig(), notion=NotionConfig())


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateStore:
    path = tmp_path / "state.json"
    s = StateStore(path)
    monkeypatch.setattr(fleet_gate, "StateStore", lambda: s)
    return s


def test_pause_idle_enters_paused(store: StateStore) -> None:
    snap = fleet_gate.request_pause(store=store, by="test")
    assert snap["pause_requested"] is True
    assert snap["paused"] is True
    assert fleet_gate.should_start_work(store=store) is False


def test_pause_waits_while_busy(store: StateStore) -> None:
    fleet_gate.set_busy("admin_manager", True, store=store)
    snap = fleet_gate.request_pause(store=store)
    assert snap["pause_requested"] is True
    assert snap["paused"] is False
    assert snap["busy"] == ["admin_manager"]
    fleet_gate.set_busy("admin_manager", False, store=store)
    assert fleet_gate.is_paused(store=store) is True


def test_dispatch_slot_blocks_when_paused(store: StateStore) -> None:
    fleet_gate.request_pause(store=store)
    with fleet_gate.dispatch_slot("github_manager", store=store) as allowed:
        assert allowed is False


def test_resume_clears(store: StateStore) -> None:
    fleet_gate.request_pause(store=store)
    fleet_gate.resume(store=store)
    assert fleet_gate.should_start_work(store=store) is True


def test_redeploy_cue(store: StateStore) -> None:
    fleet_gate.request_redeploy(pr_url="https://example.com/pr/1", by="test", store=store)
    pending = fleet_gate.redeploy_pending(store=store)
    assert pending is not None
    assert pending["pr_url"].endswith("/pr/1")
    text = fleet_gate.redeploy_instructions(store=store)
    assert text and "redeploy cue" in text.lower()
    fleet_gate.clear_redeploy(store=store)
    assert fleet_gate.redeploy_pending(store=store) is None


def test_base_agent_skips_when_paused(store: StateStore) -> None:
    class Tiny(BaseAgent):
        name = "tiny_specialist"

        def run(self, **kwargs):
            return {"ok": True}

    fleet_gate.request_pause(store=store)
    out = Tiny(_cfg()).execute()
    assert out is SKIPPED


def test_fleet_exempt_manager_still_runs(store: StateStore) -> None:
    class Mgr(BaseAgent):
        name = "tiny_manager"
        fleet_exempt = True

        def run(self, **kwargs):
            return {"ok": True}

    fleet_gate.request_pause(store=store)
    out = Mgr(_cfg()).execute()
    assert out == {"ok": True}
