"""Admin console Review aggregator, VM costs, and SSO allow-list."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from company_brain.admin_console import auth, costs, heartbeats, review
from company_brain.agents.gates import StateStore
from company_brain.runtime import fleet_gate
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture()
def wiki_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalWikiStore:
    root = tmp_path / "wiki"
    root.mkdir()
    store = LocalWikiStore(root=root)
    monkeypatch.setattr(review, "LocalWikiStore", lambda: store)
    return store


@pytest.fixture()
def state_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StateStore:
    path = tmp_path / "state.json"
    store = StateStore(path)
    monkeypatch.setattr(fleet_gate, "StateStore", lambda: store)
    monkeypatch.setattr(heartbeats, "StateStore", lambda: store)
    monkeypatch.setattr(costs, "StateStore", lambda: store)
    return store


def test_review_union_wiki_and_redeploy(
    wiki_store: LocalWikiStore, state_store: StateStore
) -> None:
    wiki_store.write(
        "admin/import-review/abc.md",
        MarkdownDoc(
            frontmatter={"title": "Import Review — x"},
            body="## Needs review\n\nPlease approve.\n",
        ),
    )
    wiki_store.write(
        "ops/conflict.md",
        MarkdownDoc(
            frontmatter={"title": "Conflicted", "sync_conflict": True},
            body="body\n",
        ),
    )
    fleet_gate.request_redeploy(pr_url="https://example.com/pr/9", store=state_store)
    snap = review.review_snapshot(wiki=wiki_store, state=state_store)
    kinds = {i["kind"] for i in snap["items"]}
    assert "import_review" in kinds
    assert "sync_conflict" in kinds
    assert "redeploy" in kinds
    assert snap["count"] >= 3


def test_vm_cost_estimate(state_store: StateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        costs,
        "load_admin_console_config",
        lambda: {"costs": {"vm_hourly_usd": 1.0}, "managers": [{"name": "admin_manager"}]},
    )
    monkeypatch.setattr(
        costs,
        "manager_catalog",
        lambda: [{"name": "admin_manager", "label": "Admin"}],
    )
    monkeypatch.setattr(costs, "stale_minutes", lambda: 10)
    monkeypatch.setattr(
        heartbeats,
        "manager_catalog",
        lambda: [{"name": "admin_manager", "label": "Admin"}],
    )
    monkeypatch.setattr(heartbeats, "stale_minutes", lambda: 10)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    state_store.set(
        f"{heartbeats.HEARTBEAT_PREFIX}admin_manager",
        {"name": "admin_manager", "at": now.isoformat(), "detail": "idle"},
    )
    vm = costs.vm_cost_snapshot(store=state_store, now=now)
    assert vm["enabled"] is True
    assert vm["active_managers"] == 1
    assert vm["is_estimate"] is True
    assert vm["estimate_month_usd"] > 0
    assert vm["hours_elapsed_month"] == pytest.approx(14 * 24 + 12, rel=0.01)


def test_sso_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_CONSOLE_SESSION_SECRET", "session-secret-value")
    monkeypatch.setenv("ADMIN_CONSOLE_GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("ADMIN_CONSOLE_GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(
        auth,
        "load_admin_console_config",
        lambda: {
            "admins": ["admin@acme.com"],
            "password_login": True,
            "sso": {"enabled": True, "provider": "google", "hosted_domain": "acme.com"},
        },
    )
    assert auth.email_allowed("admin@acme.com") is True
    assert auth.email_allowed("other@acme.com") is False
    assert auth.sso_enabled() is True
    token = auth.mint_session(email="admin@acme.com", now=1_000_000.0)
    assert auth.verify_session(token, now=1_000_000.0) is True
    bad = auth.mint_session(email="other@acme.com", now=1_000_000.0)
    assert auth.verify_session(bad, now=1_000_000.0) is False


def test_password_local_when_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_CONSOLE_PASSWORD", "s3cret")
    monkeypatch.setenv("ADMIN_CONSOLE_SESSION_SECRET", "session-secret-value")
    monkeypatch.setattr(
        auth,
        "load_admin_console_config",
        lambda: {"admins": ["admin@acme.com"], "password_login": True, "sso": {}},
    )
    token = auth.mint_session(email=auth.PASSWORD_LOCAL_EMAIL, now=1_000_000.0)
    assert auth.verify_session(token, now=1_000_000.0) is True


def test_auth_ready_sso_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_CONSOLE_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_CONSOLE_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("ADMIN_CONSOLE_GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ADMIN_CONSOLE_SESSION_SECRET", "session-secret-value")
    monkeypatch.setattr(
        auth,
        "load_admin_console_config",
        lambda: {
            "password_login": False,
            "admins": [],
            "sso": {"enabled": True, "provider": "google", "hosted_domain": ""},
        },
    )
    assert auth.auth_ready() is True
    assert auth.password_login_enabled() is False


def test_review_skips_empty_fixed_page(wiki_store: LocalWikiStore) -> None:
    wiki_store.write(
        "admin/weave-queue.md",
        MarkdownDoc(frontmatter={"title": "Weave Queue"}, body="# Weave Queue\n\n"),
    )
    items = review.review_items(wiki=wiki_store)
    assert not any(i.kind == "weave_queue" for i in items)
