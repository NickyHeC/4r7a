"""Sessions H/I/J: citation Query, security/warm-intro, who_knows."""

from __future__ import annotations

import json

import yaml

from company_brain.agents.engineering.linear.linear_completed.archive_gmail import (
    ArchiveGmailAgent,
)
from company_brain.agents.engineering.linear.task_bindings import TaskBinding
from company_brain.agents.operations.shared.classify import classify_message
from company_brain.agents.operations.shared.security_heuristics import security_match
from company_brain.config import load_config
from company_brain.wiki.citation_query import (
    citation_query,
    expand_result,
    granted_employee_prefixes,
)
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc
from company_brain.wiki.who_knows import rebuild_who_knows_index, suggest_people


def _msg(*, subject: str = "", from_: str = "", snippet: str = ""):
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": from_},
    ]
    return {"payload": {"headers": headers}, "snippet": snippet}


def test_security_never_archives():
    result = classify_message(
        _msg(
            subject="Security alert: unusual sign-in",
            from_="noreply@accounts.google.com",
            snippet="If you did not recently sign in, reset your password.",
        )
    )
    assert "Security" in result.domain_tags
    assert result.archive_now is False
    assert result.mark_read is False
    assert result.attention == "1. Action"


def test_security_beats_cold_archive():
    result = classify_message(
        _msg(
            subject="Urgent wire transfer / gift card request",
            from_="vendor@evil.com",
            snippet="Please send gift cards for the wire transfer today.",
        )
    )
    assert "Security" in result.domain_tags
    assert result.archive_now is False


def test_warm_intro_confirmed_only(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    # Confirmed connection in registry
    reg = {
        "version": 1,
        "by_email": {
            "alice@friend.com": {
                "slug": "alice-friend",
                "segment": "connection",
                "source": "contact",
            }
        },
        "by_domain": {},
        "updated_at": "",
    }
    store = LocalWikiStore(root=wiki)
    store.write_text("crm/_registry.json", json.dumps(reg))

    monkeypatch.setattr(
        "company_brain.crm.registry.resolve_wiki_dir",
        lambda: wiki,
    )
    # Also patch lookup path used by classify
    from company_brain.crm import registry as reg_mod

    monkeypatch.setattr(reg_mod, "resolve_wiki_dir", lambda: wiki)

    hit = classify_message(
        _msg(
            subject="Wanted to introduce you to Bob",
            from_="Alice <alice@friend.com>",
            snippet="Wanted to introduce you to Bob who builds widgets.",
        )
    )
    assert "Warm intro" in hit.domain_tags

    miss = classify_message(
        _msg(
            subject="Wanted to introduce you to Bob",
            from_="Stranger <stranger@unknown.com>",
            snippet="Wanted to introduce you to Bob who builds widgets.",
        )
    )
    assert "Warm intro" not in miss.domain_tags


def test_security_match_borderline():
    out = security_match("Please verify your account", "x@y.com", "confirm your identity")
    assert out["matched"] is True
    assert out["confidence"] == "borderline"


def test_archive_gmail_idempotent_and_requires_binding(monkeypatch):
    calls = {"n": 0}

    def fake_archive(message_id, mailbox="me"):
        calls["n"] += 1

    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.linear_completed.archive_gmail.archive",
        fake_archive,
    )
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.linear_completed.archive_gmail.record_status_change",
        lambda *a, **k: None,
    )

    class FakeStore:
        def upsert(self, binding, sync_notion=False):
            return binding

    agent = ArchiveGmailAgent(load_config())
    agent._bindings = FakeStore()  # type: ignore[assignment]

    binding = TaskBinding(
        task_id="b1",
        origin={},
        linear={},
        task_class="inbox_action",
        title="t",
        platforms={"gmail": {"message_id": "m1", "mailbox": "me"}},
    )
    r1 = agent.run(binding=binding, linear_status="Done")
    assert r1["status"] == "archived"
    assert calls["n"] == 1

    binding.platforms["gmail"]["archived"] = True
    r2 = agent.run(binding=binding, linear_status="Done")
    assert r2["status"] == "skipped"
    assert r2["reason"] == "already_archived"
    assert calls["n"] == 1

    nobind = TaskBinding(
        task_id="b2",
        origin={},
        linear={},
        task_class="inbox_action",
        title="t",
        platforms={},
    )
    r3 = agent.run(binding=nobind, linear_status="Done")
    assert r3["reason"] == "no_gmail_binding"

    wrong = TaskBinding(
        task_id="b3",
        origin={},
        linear={},
        task_class="other",
        title="t",
        platforms={"gmail": {"message_id": "m2"}},
    )
    r4 = agent.run(binding=wrong, linear_status="Done")
    assert r4["reason"] == "not_inbox_task_binding"


def test_citation_query_grants_and_cite_shape(tmp_path, monkeypatch):
    company = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    employee.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)
    (config_dir / "wiki.yaml").write_text("sections: {}\n")
    (config_dir / "notion.yaml").write_text("teamspaces: {}\n")
    (config_dir / "members.yaml").write_text(
        yaml.safe_dump(
            {
                "members": {
                    "admin": {"email": "a@co.com", "role": "admin"},
                    "alice": {
                        "email": "alice@co.com",
                        "role": "member",
                        "query_grants": {"bob": ["alice/work-log/"]},
                    },
                    "bob": {"email": "bob@co.com", "role": "member"},
                }
            }
        )
    )

    cstore = LocalWikiStore(root=company)
    cstore.write(
        "engineering/runway.md",
        MarkdownDoc(
            frontmatter={
                "title": "Runway",
                "sync": "company",
                "notion_page_id": "abc-123",
            },
            body="# Runway\n\nCash runway is 18 months.\n",
        ),
    )
    cstore.write(
        "admin/secret.md",
        MarkdownDoc(
            frontmatter={"title": "Secret", "sync": "admin_only"},
            body="# Secret\n\nHidden.\n",
        ),
    )
    (employee / "alice" / "work-log").mkdir(parents=True)
    (employee / "alice" / "work-log" / "2026-Q2.md").write_text(
        "---\ntitle: Alice Q2\nsync: private\nmember: alice\n---\n"
        "# Alice Q2\n\nShipped runway dashboard.\n"
    )

    # bob can see alice work-log via grants; not admin_only company
    result = citation_query(
        "runway",
        as_member="bob",
        admin_bypass=False,
        with_people_hints=False,
    )
    paths = {h.rel_path for h in result.hits}
    assert "engineering/runway.md" in paths
    assert "admin/secret.md" not in paths
    runway = next(h for h in result.hits if h.rel_path == "engineering/runway.md")
    assert runway.citation.startswith("https://www.notion.so/")
    assert any(h.member == "alice" for h in result.hits)

    denied = expand_result(
        "admin/secret.md",
        as_member="bob",
        admin_bypass=False,
        volume="company",
    )
    assert denied["status"] == "denied"

    admin = citation_query("secret", as_member="admin", admin_bypass=True, with_people_hints=False)
    assert any(h.rel_path == "admin/secret.md" for h in admin.hits)

    grants = granted_employee_prefixes("bob", admin_bypass=False)
    assert ("alice", "alice/work-log/") in grants


def test_who_knows_excludes_connect(tmp_path, monkeypatch):
    company = tmp_path / "wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)
    (config_dir / "members.yaml").write_text(
        yaml.safe_dump(
            {
                "members": {
                    "nicky": {
                        "email": "n@co.com",
                        "bindings": {"slack_user_id": "U1"},
                    }
                }
            }
        )
    )
    (config_dir / "operations.yaml").write_text("who_knows:\n  min_score: 1.0\n")
    channels_path = config_dir / "slack_channels.json"
    channels_path.write_text(
        json.dumps(
            {
                "version": 1,
                "channels": {
                    "C_CONNECT": {"is_connect": True, "name": "ext"},
                    "C_INT": {"is_connect": False, "name": "eng"},
                },
            }
        )
    )
    monkeypatch.setattr(
        "company_brain.agents.operations.slack.channels_config.CHANNELS_FILE",
        channels_path,
    )

    store = LocalWikiStore(root=company)
    store.write(
        "people/nicky.md",
        MarkdownDoc(
            frontmatter={"title": "Nicky"},
            body="# Nicky\n\nExpertise in kubernetes and runway planning.\n",
        ),
    )
    # Connect channel routing — must be ignored
    routing = company / "operations" / "slack" / "routing" / "x"
    routing.mkdir(parents=True)
    (routing / "1.json").write_text(
        json.dumps(
            {
                "channel": "C_CONNECT",
                "extracted": {
                    "participants": ["U1"],
                    "text_preview": "kubernetes deploy secrets",
                },
            }
        )
    )
    # Internal channel — counted
    (routing / "2.json").write_text(
        json.dumps(
            {
                "channel": "C_INT",
                "extracted": {
                    "participants": ["U1"],
                    "text_preview": "kubernetes deploy secrets",
                },
            }
        )
    )

    out = rebuild_who_knows_index(store=store, sync=False)
    assert out["status"] == "ok"
    hints = suggest_people("kubernetes runway", store=store, threshold=1.0)
    assert hints
    assert hints[0]["member"] == "nicky"
