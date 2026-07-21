"""Tests for growth workstreams (activity, content, competitor, leads)."""

from __future__ import annotations

from company_brain.agents.growth.activity.event_plan import EventPlanAgent
from company_brain.agents.growth.activity.event_register import EventRegisterAgent
from company_brain.agents.growth.activity.event_wrap import EventWrapAgent
from company_brain.agents.growth.activity.partnership_brief import PartnershipBriefAgent
from company_brain.agents.growth.activity_manager import ActivityManager
from company_brain.agents.growth.competitor.discover import CompetitorDiscoverAgent
from company_brain.agents.growth.content.draft_writer import DraftWriterAgent
from company_brain.agents.growth.content.published_pull import PublishedPullAgent
from company_brain.agents.growth.lead_manager import LeadManager
from company_brain.agents.growth.leads.lead_research import LeadResearchAgent
from company_brain.agents.growth.leads.queue import enqueue_lead_job, list_pending_jobs
from company_brain.config import load_config
from company_brain.crm.contacts import write_contact
from company_brain.crm.schema import ContactEntity
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.wiki.store import LocalWikiStore


def _cfg():
    return load_config()


def test_event_register_plan_partner_wrap(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    reg = EventRegisterAgent(_cfg()).run(
        name="Demo Night",
        date="2026-08-01",
        notes="Slack thread notes",
        source="cli",
        notify=False,
    )
    assert reg["status"] == "ok"
    assert reg["slug"] == "demo-night"
    store = LocalWikiStore(root=wiki)
    assert store.exists("growth/activity/event/demo-night.md")

    plan = EventPlanAgent(_cfg()).run(slug="demo-night")
    assert plan["status"] == "ok"
    body = store.read("growth/activity/event/demo-night.md").body
    assert "Venue" in body

    partner = PartnershipBriefAgent(_cfg()).run(
        slug="demo-night",
        partner_name="Acme Labs",
        partner_bio="DevTools co",
    )
    assert partner["status"] == "ok"
    assert store.exists("growth/activity/event/demo-night-partner-acme-labs.md")

    wrap = EventWrapAgent(_cfg()).run(
        slug="demo-night",
        attendees_csv="email,name,company\na@b.com,Ann,Beta\n",
        notify=False,
    )
    assert wrap["status"] == "ok"
    assert wrap["lead_job"]
    assert list_pending_jobs()
    assert store.exists("growth/content/draft/demo-night-x-wrap.md")


def test_activity_manager_plans_registered(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    EventRegisterAgent(_cfg()).run(name="Mixer", source="cli", notify=False)
    out = ActivityManager(_cfg()).run(once=True)
    assert out["status"] == "ok"
    assert "mixer" in out["planned"]
    fm = LocalWikiStore(root=wiki).read("growth/activity/event/mixer.md").frontmatter
    assert fm["event_status"] == "planning"


def test_lead_research_crm_first(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    ensure_crm_seeds()

    write_contact(
        ContactEntity(
            slug="known-acme-com",
            title="Known",
            segment="connection",
            canonical_email="known@acme.com",
            main_connection_employee="nicky",
        )
    )

    job = enqueue_lead_job(
        source="attendee_csv",
        label="event:test",
        payload={
            "csv_text": (
                "email,name,company\n"
                "known@acme.com,Known,Acme\n"
                "new@startup.io,New Person,Startup\n"
                "onlyhandle\n"
            )
        },
    )
    result = LeadResearchAgent(_cfg()).run(job=job, notify=False)
    assert result["status"] == "ok"
    assert result["created"] == 1
    assert result["updated"] == 1
    assert any("no_email" in s for s in result["skipped"])

    store = LocalWikiStore(root=wiki)
    assert store.exists("crm/contact/new-startup-io.md")
    lead_fm = store.read("crm/contact/new-startup-io.md").frontmatter
    assert lead_fm["segment"] == "lead"
    conn = store.read("crm/contact/known-acme-com.md")
    assert conn.frontmatter["segment"] == "connection"
    assert "Lead research note" in conn.body


def test_lead_manager_empty_queue(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    out = LeadManager(_cfg()).run(once=True)
    assert out["status"] == "skipped"


def test_draft_and_published_pull(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    draft = DraftWriterAgent(_cfg()).run(
        channel="x",
        instructions="We shipped a thing",
        title="Ship note",
    )
    assert draft["status"] == "ok"
    store = LocalWikiStore(root=wiki)
    assert store.exists(draft["wiki_path"])

    pull = PublishedPullAgent(_cfg()).run(
        items=[
            {
                "channel": "x",
                "title": "Ship note",
                "url": "https://example.com/x",
                "text": "We shipped a thing",
            }
        ],
        force=True,
    )
    assert pull["ingested"] == 1
    assert pull["retired_drafts"]
    assert store.exists("growth/content/published.md")
    assert store.exists("growth/content/voice/company.md")
    fm = store.read(draft["wiki_path"]).frontmatter
    assert fm["status"] == "posted"


def test_competitor_discover_seeds_from_keywords(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(
        "company_brain.agents.growth.competitor.discover.competitor_keywords",
        lambda: ["smolvm", "microvm sandbox"],
    )
    out = CompetitorDiscoverAgent(_cfg()).run(force=True)
    assert out["status"] == "ok"
    assert out["seeded"] >= 1
    store = LocalWikiStore(root=wiki)
    assert store.exists("growth/competitor/_index.md")
    assert store.exists("growth/competitor/smolvm.md")


def test_wiki_growth_command_register(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    from company_brain.agents.operations.slack import wiki_commands

    monkeypatch.setattr(wiki_commands, "ask_wiki_allowed", lambda _c: True)
    replies: list[str] = []

    def _reply(_c, _t, text):
        replies.append(text)
        return {"status": "replied", "ts": "1"}

    monkeypatch.setattr(wiki_commands, "_reply", _reply)

    out = wiki_commands.handle_wiki_command(
        channel_id="C1",
        thread_ts="1.0",
        command="register",
        slack_user_id="U1",
        text="register event Office Hours on 2026-09-01",
    )
    assert out["status"] == "replied"
    assert LocalWikiStore(root=wiki).exists("growth/activity/event/office-hours.md")
    assert "office-hours" in replies[0]
