"""Tests for Slack thread → raw/entries distill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from company_brain.agents.operations.slack.routing import SlackRoutingRecord, SlackRoutingStore
from company_brain.agents.operations.slack.thread_absorb import ThreadAbsorbAgent
from company_brain.config import AppConfig, NotionConfig, WikiConfig


def _cfg() -> AppConfig:
    return AppConfig(wiki=WikiConfig(), notion=NotionConfig())


def test_thread_absorb_enqueues_closed_thread(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    store = SlackRoutingStore(wiki_dir=wiki)
    now = datetime.now(timezone.utc).isoformat()
    record = SlackRoutingRecord(
        channel="CINTERNAL",
        thread_ts="1710000000.000100",
        created_at=now,
        updated_at=now,
        kind="fyi",
        customer=False,
        extracted={"text_preview": "we should document the restore prefetch flag"},
        handled={"closed": now},
    )
    store.write(record)

    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_connect_channel",
        lambda _c: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_out_of_scope",
        lambda _c: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.slack_client.slack_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.slack_client.fetch_thread_replies",
        lambda _c, _t: [
            {"user": "U1", "text": "Restore stalls after manifest load on NFS."},
            {
                "user": "U2",
                "text": "Set CKPT_PREFETCH=4 and it completes. Document that in the runbook.",
            },
        ],
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.resolve_raw_dir",
        lambda: tmp_path / "raw",
    )

    agent = ThreadAbsorbAgent(_cfg())
    agent._routing = store
    out = agent.run(force=True)
    assert out["enqueued"] == 1
    entries = list((tmp_path / "raw" / "entries").glob("*.md"))
    assert len(entries) == 1
    text = entries[0].read_text()
    assert "CKPT_PREFETCH" in text
    assert "source_type: slack" in text

    # idempotent
    out2 = agent.run(force=True)
    assert out2["enqueued"] == 0


def test_thread_absorb_skips_connect(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    store = SlackRoutingStore(wiki_dir=wiki)
    now = datetime.now(timezone.utc).isoformat()
    store.write(
        SlackRoutingRecord(
            channel="CCONNECT",
            thread_ts="1710000000.000200",
            created_at=now,
            updated_at=now,
            customer=False,
            handled={"closed": now},
            extracted={"text_preview": "hello customer thread with enough words here"},
        )
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_connect_channel",
        lambda c: c == "CCONNECT",
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_out_of_scope",
        lambda _c: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.slack_client.slack_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.resolve_raw_dir",
        lambda: tmp_path / "raw",
    )
    agent = ThreadAbsorbAgent(_cfg())
    agent._routing = store
    out = agent.run(force=True)
    assert out["enqueued"] == 0
    assert not (tmp_path / "raw" / "entries").exists() or not list(
        (tmp_path / "raw" / "entries").glob("*.md")
    )


def test_open_thread_needs_min_age(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    store = SlackRoutingStore(wiki_dir=wiki)
    recent = datetime.now(timezone.utc).isoformat()
    store.write(
        SlackRoutingRecord(
            channel="CINTERNAL",
            thread_ts="1710000000.000300",
            created_at=recent,
            updated_at=recent,
            customer=False,
            extracted={
                "text_preview": "enough words in this open thread for absorb eligibility check"
            },
        )
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_connect_channel",
        lambda _c: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.channels_config.is_out_of_scope",
        lambda _c: False,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.slack_client.slack_is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.cfg.thread_absorb_min_age_hours",
        lambda: 12,
    )
    agent = ThreadAbsorbAgent(_cfg())
    agent._routing = store
    out = agent.run(force=True)
    assert out["enqueued"] == 0

    old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rec = store.read("CINTERNAL", "1710000000.000300")
    assert rec is not None
    rec.updated_at = old
    store.write(rec, touch_updated=False)
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.slack_client.fetch_thread_replies",
        lambda *_a, **_k: [
            {
                "user": "U1",
                "text": (
                    "Aged open thread with enough words to distill into raw entries "
                    "for the encyclopedia absorb pipeline after the minimum age gate."
                ),
            }
        ],
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.thread_absorb.resolve_raw_dir",
        lambda: tmp_path / "raw",
    )
    out2 = agent.run(force=True)
    assert out2["enqueued"] == 1
