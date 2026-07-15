"""Tests for employee wiki Notion sync routing (Phase C)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from company_brain.config import AppConfig, NotionConfig, load_config
from company_brain.notion.sync_routing import (
    resolve_sync_parent,
    should_skip_notion_mirror,
)
from company_brain.wiki.employee_notion_sync import EmployeeNotionSync
from company_brain.wiki.employee_publish import write_employee_wiki_page
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.store import MarkdownDoc


@pytest.fixture
def notion_config():
    return AppConfig(
        wiki=load_config().wiki,
        notion=NotionConfig(
            root_page_id="root-page",
            teamspaces={
                "admin": "admin-parent",
                "company": "company-parent",
                "member_alice": "alice-parent",
            },
            section_teamspace={"finance": "admin_only"},
        ),
    )


def test_not_synced_skips_mirror(notion_config):
    fm = {"sync": "not_synced", "member": "alice"}
    assert should_skip_notion_mirror(fm, notion_config) is True


def test_private_resolves_member_teamspace(notion_config, tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "members.yaml").write_text(
        "members:\n  alice:\n    notion_teamspace: member_alice\n"
    )
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)

    parent = resolve_sync_parent({"sync": "private", "member": "alice"}, notion_config)
    assert parent == "alice-parent"


def test_admin_only_sync_mirrors_to_admin_teamspace(notion_config):
    parent = resolve_sync_parent({"sync": "admin_only", "member": "alice"}, notion_config)
    assert parent == "admin-parent"
    assert should_skip_notion_mirror({"sync": "admin_only"}, notion_config) is False


def test_company_section_admin_only_still_skips(notion_config):
    fm = {"section": "finance/secrets"}
    assert should_skip_notion_mirror(fm, notion_config) is True


def test_location_routing(notion_config):
    notion_config.notion.teamspaces["engineering"] = "eng-parent"
    parent = resolve_sync_parent({"sync": "location:engineering"}, notion_config)
    assert parent == "eng-parent"


def test_employee_notion_sync_skips_not_synced(notion_config, tmp_path):
    store = LocalEmployeeWikiStore(root=tmp_path)
    store.write(
        "alice/secret.md",
        MarkdownDoc(
            frontmatter={"title": "Secret", "member": "alice", "sync": "not_synced"},
            body="# Secret\n",
        ),
    )
    syncer = EmployeeNotionSync(store=store, config=notion_config, client=MagicMock())
    assert syncer.sync_doc("alice/secret.md") is None


def test_employee_notion_sync_creates_under_private_parent(notion_config, tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "members.yaml").write_text(
        "members:\n  alice:\n    notion_teamspace: member_alice\n",
    )
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)

    store = LocalEmployeeWikiStore(root=tmp_path / "ew")
    store.write(
        "alice/_index.md",
        MarkdownDoc(
            frontmatter={"title": "Current", "member": "alice", "sync": "private"},
            body="# Current\n",
        ),
    )
    client = MagicMock()
    client.create_page.return_value = MagicMock(stdout="", json_data={"id": "notion-page-1"})
    client.update_page.return_value = MagicMock()

    syncer = EmployeeNotionSync(store=store, config=notion_config, client=client)
    page_id = syncer.sync_doc("alice/_index.md")

    assert page_id == "notion-page-1"
    client.create_page.assert_called_once()
    assert client.create_page.call_args[0][0] == "alice-parent"


def test_write_employee_wiki_page_mirrors_when_enabled(notion_config, tmp_path, monkeypatch):
    ew = tmp_path / "ew"
    store = LocalEmployeeWikiStore(root=ew)
    monkeypatch.setattr(
        "company_brain.wiki.employee_notion_sync.sync_employee_doc",
        lambda rel_path, store=None, force=False: "notion-99",
    )
    page_id = write_employee_wiki_page(
        "alice/note.md",
        "Note",
        "# Note\n",
        member="alice",
        sync="private",
        store=store,
        mirror_notion=True,
    )
    assert page_id == "notion-99"


def test_onboarding_agent_bootstrap(tmp_path, monkeypatch):
    from company_brain.agents.employee_wiki.employee_wiki_onboarding import (
        EmployeeWikiOnboardingAgent,
    )

    company = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    employee.mkdir()
    config_dir.mkdir()
    (config_dir / "members.yaml").write_text("members:\n  alice:\n    email: a@co.com\n")
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.members_config.CONFIG_DIR", config_dir)

    agent = EmployeeWikiOnboardingAgent(load_config())
    with patch(
        "company_brain.agents.employee_wiki.employee_wiki_onboarding.NotionClient",
    ) as mock_client_cls:
        mock_client_cls.return_value.check_auth.return_value = False
        result = agent.run(member_key="alice", mirror_notion=True)

    assert result["status"] == "ok"
    assert LocalEmployeeWikiStore(root=employee).exists("alice/_index.md")
