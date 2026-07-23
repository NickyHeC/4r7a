"""Sessions E+F: absorb lanes, burst distill, @wiki planner, sync now."""

from __future__ import annotations

from datetime import datetime, timezone

from company_brain.agents.operations.slack.burst_distill import (
    distill_bursts,
    segment_bursts,
    should_burst,
)
from company_brain.agents.operations.slack.wiki_planner import MAX_FETCHES, plan_and_fetch
from company_brain.ingestion.entry import RawEntry
from company_brain.wiki.absorb_lanes import (
    lane_for_entry,
    soft_cap_prompt_blurb,
    sort_entries_by_lane,
)
from company_brain.wiki.platform_sync import SYNC_ALIASES, sync_platform
from company_brain.wiki.project_registry import parse_registry_body, prefixes_for_channel


def _entry(eid: str, tags: list[str], *, lane: str | None = None, ts: str = "") -> RawEntry:
    meta = {}
    if lane:
        meta["absorb_lane"] = lane
    return RawEntry(
        id=eid,
        source_type="test",
        source_id=eid,
        title=eid,
        content="body",
        tags=tags,
        metadata=meta,
        timestamp=datetime.fromisoformat(ts) if ts else datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_lane_priority_urgent_before_bulk():
    entries = [
        _entry("b", ["bulk"], ts="2026-07-01T00:00:00+00:00"),
        _entry("u", ["urgent"], ts="2026-07-02T00:00:00+00:00"),
        _entry("n", ["slack"], ts="2026-07-03T00:00:00+00:00"),
    ]
    ordered = sort_entries_by_lane(entries)
    assert [e.id for e in ordered] == ["u", "n", "b"]
    assert lane_for_entry(entries[0]) == "bulk"
    assert lane_for_entry(entries[1]) == "urgent"


def test_soft_cap_prompt_mentions_range():
    blurb = soft_cap_prompt_blurb()
    assert "800" in blurb and "1200" in blurb
    assert "Soft" in blurb or "soft" in blurb.lower()


def test_burst_on_long_thread():
    msgs = []
    base = 1_700_000_000.0
    for i in range(14):
        msgs.append(
            {
                "user": f"U{i % 3}",
                "text": "Should we ship it?" if i % 4 == 0 else f"note {i}",
                "ts": str(base + i * 60),
            }
        )
    # Insert a long gap to force a second burst
    msgs[7]["ts"] = str(base + 7 * 60 + 3600)
    assert should_burst(msgs)
    bursts = segment_bursts(msgs)
    assert len(bursts) >= 2
    md = distill_bursts(msgs)
    assert "## Burst distill" in md
    assert "question" in md.lower() or "**question:**" in md


def test_burst_skipped_for_short_thread():
    msgs = [{"user": "U1", "text": "hi", "ts": "1"}, {"user": "U2", "text": "yo", "ts": "2"}]
    assert not should_burst(msgs)
    assert "## Burst distill" not in distill_bursts(msgs)


def test_project_registry_channel_prefixes():
    body = """
| key | wiki_prefixes | channels | teamspace |
|-----|---------------|----------|-----------|
| acme | product/,engineering/ | C0123 | company |
"""
    reg = parse_registry_body(body)
    assert "acme" in reg
    assert "product/" in reg["acme"].wiki_prefixes


def test_planner_fail_closed(monkeypatch):
    calls = {"wiki": 0, "crm": 0, "practices": 0}

    def boom():
        raise RuntimeError("fail")

    def wiki_ok(*_a, **_k):
        calls["wiki"] += 1
        return [
            {
                "rel_path": "engineering/x.md",
                "title": "X",
                "snippet": "hello",
                "score": 1.0,
                "notion_page_id": "",
                "source": "wiki",
            }
        ]

    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_planner._fetch_wiki",
        wiki_ok,
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_planner._fetch_crm",
        lambda **_k: boom(),
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.wiki_planner._fetch_practices",
        lambda **_k: boom(),
    )
    hits = plan_and_fetch("hello", channel_id="C999")
    assert hits
    assert hits[0]["rel_path"] == "engineering/x.md"
    assert MAX_FETCHES == 3


def test_sync_platform_unknown():
    out = sync_platform("nope")
    assert out["status"] == "error"
    assert "notion" in out["supported"]
    assert "notion" in SYNC_ALIASES


def test_prefixes_for_channel_from_registry(tmp_path, monkeypatch):
    from company_brain.wiki.store import LocalWikiStore, MarkdownDoc

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setattr(
        "company_brain.wiki.project_registry.channel_project_key",
        lambda _cid: None,
    )
    store = LocalWikiStore(root=wiki)
    store.write(
        "operations/project-registry.md",
        MarkdownDoc(
            frontmatter={"title": "Project Registry"},
            body=(
                "| key | wiki_prefixes | channels | teamspace |\n"
                "|-----|---------------|----------|-----------|\n"
                "| beta | growth/ | CABC | company |\n"
            ),
        ),
    )
    assert prefixes_for_channel("CABC", store=store) == ["growth/"]
