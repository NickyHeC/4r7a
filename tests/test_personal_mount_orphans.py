"""Session G: personal wiki mount kind + Notion orphan discovery."""

from __future__ import annotations

import yaml

from company_brain.agents.gates import StateStore
from company_brain.agents.operations.notion.orphan_discovery import (
    OrphanDiscoveryAgent,
    collect_bound_notion_ids,
    orphan_review_path,
)
from company_brain.config import load_config
from company_brain.external_sources_config import load_external_sources, save_external_sources
from company_brain.wiki.duplicate_detect import detect_external_duplicates
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.external_promote import promote_external_mount
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def test_personal_mount_promotes_to_employee_wiki(tmp_path, monkeypatch):
    company = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    employee.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("company_brain.external_sources_config.CONFIG_DIR", config_dir)
    (config_dir / "operations.yaml").write_text(
        yaml.safe_dump(
            {
                "external_wiki": {
                    "import": {"require_admin_approval": True},
                    "catalog": {"rebuild_on_mount": False},
                }
            }
        )
    )
    (config_dir / "external_sources.yaml").write_text("sources: {}\n")

    store = LocalWikiStore(root=company)
    source = "nicky_notes"
    import_id = "p1"
    q = f"external/_quarantine/{source}/{import_id}/"
    store.write(f"{q}notes/idea.md", MarkdownDoc(body="# Idea\n\nPersonal thought.\n"))

    report = detect_external_duplicates(
        {"notes/idea.md": store.read(f"{q}notes/idea.md").body},
        source_key=source,
        import_id=import_id,
        company_store=store,
    )
    store.write_text(f"{q}duplicate_report.json", report.serialize())

    cfg = load_external_sources()
    cfg.ensure_source(source, label="Nicky notes", kind="personal", member_key="nicky")
    save_external_sources(cfg, config_dir=config_dir)

    result = promote_external_mount(source, import_id, store=store, rebuild_catalog=False)
    assert result.promoted
    dest = result.promoted[0]
    assert dest.startswith("nicky/")
    emp = LocalEmployeeWikiStore(root=employee)
    assert emp.exists(dest)
    doc = emp.read(dest)
    assert doc.frontmatter.get("sync") == "private"
    assert doc.frontmatter.get("source") == "personal_mount"
    assert doc.frontmatter.get("member") == "nicky"
    assert not store.exists(f"external/{source}/notes/idea.md")
    mounts = load_external_sources().sources[source].mounts
    assert mounts[-1].promote_prefix == "employee_wiki/nicky/"


def test_orphan_discovery_never_auto_adopts(tmp_path, monkeypatch):
    company = tmp_path / "wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.platform_config.CONFIG_DIR",
        config_dir,
    )
    (config_dir / "operations.yaml").write_text(
        yaml.safe_dump(
            {"notion_platform": {"orphan_discovery": {"enabled": True, "admin_channel": "#admin"}}}
        )
    )
    (config_dir / "wiki.yaml").write_text("sections: {}\n")
    (config_dir / "notion.yaml").write_text(
        yaml.safe_dump(
            {
                "root_page_id": "root-1",
                "teamspaces": {"company": "root-1", "admin": ""},
            }
        )
    )
    (config_dir / "state.json").write_text("{}")

    store = LocalWikiStore(root=company)
    store.write(
        "engineering/bound.md",
        MarkdownDoc(
            frontmatter={"title": "Bound", "notion_page_id": "bound-aaa"},
            body="# Bound\n",
        ),
    )

    class FakeClient:
        def get_block_children(self, block_id: str):
            if block_id == "root-1":
                return [
                    {
                        "id": "bound-aaa",
                        "type": "child_page",
                        "child_page": {"title": "Bound"},
                    },
                    {
                        "id": "orphan-bbb",
                        "type": "child_page",
                        "child_page": {"title": "Scratch"},
                    },
                ]
            return []

    pings: list[str] = []

    class FakeNotifier:
        def emit(self, signal):
            pings.append(signal.text)
            return True

    monkeypatch.setattr(
        "company_brain.agents.operations.notion.orphan_discovery.channel_notifier",
        lambda _ch: FakeNotifier(),
    )

    agent = OrphanDiscoveryAgent(
        load_config(),
        store=store,
        client=FakeClient(),  # type: ignore[arg-type]
        state=StateStore(path=config_dir / "state.json"),
        sync=False,
    )
    out = agent.run(force=True)
    assert out["status"] == "ok"
    assert out["auto_adopted"] == 0
    assert out["orphans"] == 1
    rel = orphan_review_path("orphan-bbb")
    assert store.exists(rel)
    doc = store.read(rel)
    assert doc.frontmatter.get("orphan_status") == "open"
    assert "never auto" in doc.body.lower() or "Never auto" in doc.body
    assert "Adopt" in doc.body
    assert not any(
        "orphan-bbb" in str((store.read(p).frontmatter or {}).get("notion_page_id") or "")
        for p in store.list()
        if p.startswith("engineering/") or p.startswith("operations/")
    )
    # Bound page must not get a review
    assert not store.exists(orphan_review_path("bound-aaa"))
    assert collect_bound_notion_ids(store) >= {"bound-aaa"}
    assert pings


def test_orphan_ignored_skipped_on_rerun(tmp_path, monkeypatch):
    company = tmp_path / "wiki"
    config_dir = tmp_path / "config"
    company.mkdir()
    config_dir.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(company))
    monkeypatch.setattr("company_brain.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        "company_brain.agents.operations.notion.platform_config.CONFIG_DIR",
        config_dir,
    )
    (config_dir / "operations.yaml").write_text(
        yaml.safe_dump({"notion_platform": {"orphan_discovery": {"enabled": True}}})
    )
    (config_dir / "wiki.yaml").write_text("sections: {}\n")
    (config_dir / "notion.yaml").write_text(yaml.safe_dump({"teamspaces": {"company": "root-1"}}))
    (config_dir / "state.json").write_text("{}")
    store = LocalWikiStore(root=company)
    rel = orphan_review_path("orphan-ccc")
    store.write(
        rel,
        MarkdownDoc(
            frontmatter={
                "title": "Ignored",
                "orphan_status": "ignore",
                "notion_orphan_page_id": "orphan-ccc",
            },
            body="# Ignored\n",
        ),
    )

    class FakeClient:
        def get_block_children(self, block_id: str):
            return [
                {
                    "id": "orphan-ccc",
                    "type": "child_page",
                    "child_page": {"title": "Scratch"},
                }
            ]

    monkeypatch.setattr(
        "company_brain.agents.operations.notion.orphan_discovery.channel_notifier",
        lambda _ch: type("N", (), {"emit": staticmethod(lambda *_a, **_k: False)})(),
    )
    agent = OrphanDiscoveryAgent(
        load_config(),
        store=store,
        client=FakeClient(),  # type: ignore[arg-type]
        state=StateStore(path=config_dir / "state.json"),
        sync=False,
    )
    out = agent.run(force=True)
    assert out["orphans"] == 0
    assert out["auto_adopted"] == 0
