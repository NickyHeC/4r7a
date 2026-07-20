"""Tests for admin console auth, heartbeats, wiki ops, dispatch allow-list."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from company_brain.admin_console import auth, heartbeats
from company_brain.admin_console.audit import append_event, ledger_path
from company_brain.admin_console.dispatch import DispatchError, run_dispatch
from company_brain.agents.gates import StateStore


@pytest.fixture()
def state_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateStore:
    path = tmp_path / "state.json"
    store = StateStore(path)
    monkeypatch.setattr(heartbeats, "StateStore", lambda: store)
    return store


def test_password_and_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_CONSOLE_PASSWORD", "s3cret")
    monkeypatch.setenv("ADMIN_CONSOLE_SESSION_SECRET", "session-secret-value")
    assert auth.password_configured() is True
    assert auth.verify_password("s3cret") is True
    assert auth.verify_password("wrong") is False
    token = auth.mint_session(now=1_000_000.0)
    assert auth.verify_session(token, now=1_000_000.0) is True
    assert auth.verify_session(token, now=1_000_000.0 + auth.SESSION_TTL_SECONDS + 1) is False
    assert auth.verify_session("not.a.token") is False


def test_heartbeat_status_rows(state_store: StateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        heartbeats,
        "manager_catalog",
        lambda: [{"name": "admin_manager", "label": "Admin"}],
    )
    monkeypatch.setattr(heartbeats, "stale_minutes", lambda: 10)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    rows = heartbeats.status_rows(store=state_store, now=now)
    assert rows[0]["state"] == "no_heartbeat"

    heartbeats.record_heartbeat("admin_manager", detail="idle", store=state_store)
    # Patch stored timestamp to known value
    state_store.set(
        f"{heartbeats.HEARTBEAT_PREFIX}admin_manager",
        {"name": "admin_manager", "at": now.isoformat(), "detail": "idle"},
    )
    rows = heartbeats.status_rows(store=state_store, now=now)
    assert rows[0]["state"] == "ok"

    old = (now - timedelta(minutes=15)).isoformat()
    state_store.set(
        f"{heartbeats.HEARTBEAT_PREFIX}admin_manager",
        {"name": "admin_manager", "at": old, "detail": "idle"},
    )
    rows = heartbeats.status_rows(store=state_store, now=now)
    assert rows[0]["state"] == "stale"


def test_audit_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("company_brain.admin_console.audit.CONFIG_DIR", tmp_path)
    append_event("login_ok", who="test")
    path = ledger_path()
    assert path.exists()
    row = json.loads(path.read_text().strip())
    assert row["kind"] == "login_ok"


def test_dispatch_not_allowlisted() -> None:
    with pytest.raises(DispatchError, match="not allow-listed"):
        run_dispatch("no_such_job_ever")


def test_wiki_ops_save_uses_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    from company_brain.admin_console import wiki_ops

    called: dict = {}

    def fake_write(rel_path, title, body, **kwargs):
        called["args"] = (rel_path, title, body)
        called["kwargs"] = kwargs
        return None

    monkeypatch.setattr(wiki_ops, "write_wiki_page", fake_write)
    monkeypatch.setattr(wiki_ops.audit, "append_event", lambda *a, **k: None)

    out = wiki_ops.save_page("admin/test-page.md", "Test Page", "# Hello\n", sync=False)
    assert out["status"] == "ok"
    assert called["args"][0] == "admin/test-page.md"
    assert called["kwargs"]["mode"] == "update"
    assert called["kwargs"]["sync"] is False


def test_fastapi_app_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    monkeypatch.setenv("ADMIN_CONSOLE_PASSWORD", "s3cret")
    monkeypatch.setenv("ADMIN_CONSOLE_SESSION_SECRET", "session-secret-value")
    from fastapi.testclient import TestClient

    from company_brain.admin_console.app import create_app

    client = TestClient(create_app())
    r = client.get("/status", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")

    bad = client.post("/login", data={"password": "nope"}, follow_redirects=False)
    assert bad.status_code == 303
    assert "Invalid" in bad.headers.get("location", "") or "flash=err" in bad.headers.get(
        "location", ""
    )

    ok = client.post("/login", data={"password": "s3cret"}, follow_redirects=False)
    assert ok.status_code == 303
    assert ok.headers.get("location") == "/status"
    assert auth.COOKIE_NAME in ok.cookies

    status = client.get("/status")
    assert status.status_code == 200
    assert b"Agent status" in status.content

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
