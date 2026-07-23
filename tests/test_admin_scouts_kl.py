"""Session K/L — Ramp reconcile helpers, Discord progress dedupe, admin scouts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from company_brain.agents.gates import StateStore
from company_brain.agents.product.progress.compile import (
    compile_progress_rows,
    dedupe_feature_list,
    extract_discord_feature_titles,
    titles_fuzzy_match,
)
from company_brain.llm.reconcile import sum_vendor_llm_spend
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture
def wiki_env(tmp_path: Path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr("company_brain.config.resolve_wiki_dir", lambda: wiki)
    return wiki


def test_sum_vendor_includes_ramp(monkeypatch):
    monkeypatch.setattr(
        "company_brain.llm.reconcile._mercury_llm_spend",
        lambda start, end: {"anthropic": 10.0},
    )
    monkeypatch.setattr(
        "company_brain.llm.reconcile._ramp_llm_spend",
        lambda start, end: {"openai": 5.0, "anthropic": 2.0},
    )
    result = sum_vendor_llm_spend(month="2026-07")
    assert result["total_usd"] == 17.0
    assert "mercury" in result["sources"]
    assert "ramp" in result["sources"]
    assert result["by_source"]["ramp"]["openai"] == 5.0
    assert result["by_vendor"]["anthropic"] == 12.0


def test_discord_fuzzy_dedupe_and_evidence_only():
    assert titles_fuzzy_match("Fast Search", "fast-search filters")
    feats = dedupe_feature_list(["Search", "search filters", "Billing"])
    assert feats[0] == "Search"
    assert "Billing" in feats
    assert len(feats) == 2

    log = (
        "# Feature requests\n"
        "- **Search v2** — discord request from community\n"
        "- **Unrelated** — email only\n"
    )
    titles = extract_discord_feature_titles(log)
    assert any(titles_fuzzy_match("Search", t) for t in titles)

    rows = compile_progress_rows(
        ["Search", "Billing"],
        github={"open_pr": "", "branch_status": "", "feature_update": ""},
        linear_projects=[],
        discord_titles=["Search v2 from Discord"],
    )
    by_f = {r["feature"]: r for r in rows}
    assert by_f["Search"]["discord"] != "—"
    assert by_f["Search"]["status"] == "unknown"  # Discord never sets SoT
    assert by_f["Billing"]["discord"] == "—"


def test_process_scout_review_only(wiki_env, monkeypatch):
    from company_brain.agents.admin.process_scout import ProcessScoutAgent

    monkeypatch.setattr(
        "company_brain.agents.admin.process_scout.wiki_admin_notifier",
        lambda: type("N", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    )
    result = ProcessScoutAgent(MagicMock()).run(month="2026-06", sync=False)
    assert result["auto_merged"] == 0
    assert result["review_only"] is True
    store = LocalWikiStore(root=wiki_env)
    assert store.exists("admin/process-scout/2026-06.md")
    body = store.read("admin/process-scout/2026-06.md").body
    assert "Never auto-merge" in body


def test_self_heal_queues_never_merges(wiki_env, tmp_path, monkeypatch):
    from company_brain.agents.admin.self_heal import SelfHealAgent

    monkeypatch.setattr(
        "company_brain.agents.admin.self_heal.wiki_admin_notifier",
        lambda: type("N", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.self_heal.self_heal_config",
        lambda: {
            "enabled": True,
            "draft_pr": True,
            "sandbox_first": True,
            "queue_on_fail": True,
        },
    )
    agent = SelfHealAgent(MagicMock(), store=StateStore(path=tmp_path / "self_heal_state.json"))
    result = agent.run(
        agent_name="open_pr",
        reason="verify_rework",
        detail="missing table unique",
        sync=False,
    )
    assert result["status"] == "ok"
    assert result["auto_merged"] is False
    assert result["queued"] is True
    assert result["pr_url"] is None  # no head → no PR
    store = LocalWikiStore(root=wiki_env)
    assert "Self-heal proposal" in store.read("admin/weave-queue.md").body


def test_offboard_checklist_no_workspace_deletion(wiki_env, monkeypatch):
    from company_brain.agents.hr.employee_offboarding import EmployeeOffboardingAgent
    from company_brain.members_config import MemberBindings, MembersConfig, MemberSpec

    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.append_hiring_log",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.hr_notifier",
        lambda: type("N", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    )
    members = MembersConfig(
        members={
            "bob": MemberSpec(
                email="bob@co.com",
                bindings=MemberBindings(slack_user_id="UBOB"),
            )
        }
    )
    monkeypatch.setattr(
        "company_brain.agents.hr.employee_offboarding.load_members_config",
        lambda: members,
    )
    result = EmployeeOffboardingAgent(MagicMock()).run(member_key="bob")
    body = LocalWikiStore(root=wiki_env).read(result["wiki_path"]).body
    assert "no API deletion" in body
    assert "Workspace / Notion account deletion APIs" in body
    assert "confirm-offboard" in body


def test_social_profiles_linkedin_only(tmp_path, monkeypatch):
    from company_brain.agents.hr import hr_config

    cfg = tmp_path / "hr.yaml"
    cfg.write_text(
        "social_profiles:\n"
        "  - platform: linkedin\n"
        "    puller: linkedin.pull\n"
        "    enabled: true\n"
        "  - platform: x\n"
        "    puller: null\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hr_config, "CONFIG_DIR", tmp_path)
    profiles = hr_config.social_profiles()
    assert any(p["platform"] == "linkedin" for p in profiles)
    assert hr_config.implemented_social_pullers() == frozenset({"linkedin"})


def test_wiki_ops_and_doc_hygiene_review_pages(wiki_env, monkeypatch):
    from company_brain.agents.admin.doc_hygiene import DocHygieneAgent
    from company_brain.agents.admin.wiki_ops_audit import WikiOpsAuditAgent

    silent = type("N", (), {"emit": staticmethod(lambda *a, **k: None)})()
    monkeypatch.setattr(
        "company_brain.agents.admin.wiki_ops_audit.wiki_admin_notifier", lambda: silent
    )
    monkeypatch.setattr(
        "company_brain.agents.admin.doc_hygiene.wiki_admin_notifier", lambda: silent
    )
    store = LocalWikiStore(root=wiki_env)
    store.write(
        "product/feature.md",
        MarkdownDoc(
            frontmatter={"title": "Features", "sync": "company"},
            body="## Features\n\n- Search\n",
        ),
    )
    store.write(
        "orphan-thin.md",
        MarkdownDoc(frontmatter={"title": "Thin"}, body="hi"),
    )

    w = WikiOpsAuditAgent(MagicMock()).run(month="2026-06", sync=False)
    assert w["auto_applied"] == 0
    assert store.exists("admin/wiki-ops/2026-06.md")

    d = DocHygieneAgent(MagicMock()).run(period="2026-Q3", sync=False)
    assert d["auto_edited"] == 0
    assert store.exists("admin/doc-hygiene/2026-Q3.md")
    assert "Never auto-edit" in store.read("admin/doc-hygiene/2026-Q3.md").body
