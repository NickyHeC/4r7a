"""Tests for external wiki mount + content catalog."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from company_brain.agents.external_wiki.content_catalog_agent import ContentCatalogAgent
from company_brain.agents.external_wiki.external_wiki_import import ExternalWikiImportAgent
from company_brain.config import load_config
from company_brain.external_sources_config import load_external_sources
from company_brain.wiki.content_catalog import build_content_catalog, render_catalog_markdown
from company_brain.wiki.duplicate_detect import detect_external_duplicates
from company_brain.wiki.external_promote import promote_external_mount
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture
def wiki_env(tmp_path: Path, monkeypatch):
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
    return {"company": company, "employee": employee, "config": config_dir}


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_external_duplicate_links_company_page(wiki_env):
    store = LocalWikiStore(root=wiki_env["company"])
    body = "# Ops runbook\n\nFollow these steps.\n"
    store.write("operations/runbook.md", MarkdownDoc(frontmatter={"title": "Ops runbook"}, body=body))

    import_body = "# Ops runbook\n\nFollow these steps.\n"
    report = detect_external_duplicates(
        {"guides/runbook.md": import_body},
        source_key="friend_ops",
        import_id="ext1",
        company_store=store,
    )
    assert report.files[0].verdict == "link"
    assert report.files[0].canonical == "operations/runbook.md"


def test_external_import_quarantine_and_review(wiki_env, monkeypatch):
    store = LocalWikiStore(root=wiki_env["company"])
    store.write(
        "operations/runbook.md",
        MarkdownDoc(body="# Ops runbook\n\nFollow these steps.\n"),
    )
    zip_bytes = _make_zip(
        {
            "guides/runbook.md": "# Ops runbook\n\nFollow these steps.\n",
            "guides/new.md": "# New guide\n\nFresh content.\n",
        }
    )

    review_calls = []

    def fake_run(cls, config, **kwargs):
        review_calls.append(kwargs)
        return {"status": "ok", "review_page": "admin/external-mount-reviews/x.md"}

    monkeypatch.setattr(
        "company_brain.agents.external_wiki.external_wiki_import.get_runtime",
        lambda: type("R", (), {"run": staticmethod(fake_run)})(),
    )

    agent = ExternalWikiImportAgent(load_config())
    result = agent.run(source_key="friend_ops", zip_bytes=zip_bytes)

    assert result["status"] == "pending_review"
    assert result["source"] == "friend_ops"
    q = result["quarantine"]
    assert store.exists(f"{q}guides/new.md")
    assert store.exists(f"{q}duplicate_report.json")
    dup = json.loads(store.read_text(f"{q}duplicate_report.json"))
    paths = {f["path"]: f for f in dup["files"]}
    assert paths["guides/runbook.md"]["verdict"] == "link"
    assert review_calls
    assert "friend_ops" in load_external_sources().sources


def test_external_promote_links_and_provenance(wiki_env):
    store = LocalWikiStore(root=wiki_env["company"])
    store.write(
        "operations/runbook.md",
        MarkdownDoc(body="# Ops runbook\n\nFollow these steps.\n"),
    )
    source = "friend_ops"
    import_id = "ext99"
    q = f"external/_quarantine/{source}/{import_id}/"
    store.write(f"{q}guides/runbook.md", MarkdownDoc(body="# Ops runbook\n\nFollow these steps.\n"))
    store.write(f"{q}guides/new.md", MarkdownDoc(body="# New guide\n\nFresh content.\n"))

    from company_brain.wiki.duplicate_detect import detect_external_duplicates

    report = detect_external_duplicates(
        {
            "guides/runbook.md": store.read(f"{q}guides/runbook.md").body,
            "guides/new.md": store.read(f"{q}guides/new.md").body,
        },
        source_key=source,
        import_id=import_id,
        company_store=store,
    )
    store.write_text(f"{q}duplicate_report.json", report.serialize())

    load_external_sources().ensure_source(source, label="Friend Ops")
    from company_brain.external_sources_config import save_external_sources

    save_external_sources(load_external_sources(), config_dir=wiki_env["config"])

    result = promote_external_mount(source, import_id, store=store, rebuild_catalog=False)
    assert result.linked
    assert result.promoted
    stub = result.linked[0]
    stub_doc = store.read(stub)
    assert stub_doc.frontmatter.get("duplicate_of") == "operations/runbook.md"
    assert stub_doc.frontmatter.get("external_source") == source

    promoted = result.promoted[0]
    promoted_doc = store.read(promoted)
    assert promoted_doc.frontmatter.get("external_source") == source
    assert promoted_doc.frontmatter.get("import_id") == import_id
    assert promoted.startswith(f"external/{source}/")
    assert store.exists(f"external/{source}/_index.md")
    assert not store.exists(q.rstrip("/"))

    mounts = load_external_sources().sources[source].mounts
    assert mounts[-1].status == "active"
    assert mounts[-1].import_id == import_id


def test_content_catalog_sections(wiki_env):
    store = LocalWikiStore(root=wiki_env["company"])
    store.write("operations/a.md", MarkdownDoc(frontmatter={"title": "A"}, body="# A\n"))
    store.write(
        "external/friend_ops/guides/b.md",
        MarkdownDoc(frontmatter={"title": "B", "external_source": "friend_ops"}, body="# B\n"),
    )
    store.write(
        "admin/table-of-contents.md",
        MarkdownDoc(frontmatter={"title": "TOC"}, body="# TOC\n"),
    )

    catalog = build_content_catalog(store=store, include_employee_wiki=False)
    assert catalog.company_page_count >= 1
    assert "friend_ops" in catalog.external_mounts
    md = render_catalog_markdown(catalog)
    assert "4r7a Content Catalog" in md
    assert "external/friend_ops" in md or "friend_ops" in md


def test_catalog_agent_writes_admin_page(wiki_env, monkeypatch):
    store = LocalWikiStore(root=wiki_env["company"])
    store.write("operations/x.md", MarkdownDoc(frontmatter={"title": "X"}, body="# X\n"))

    monkeypatch.setattr(
        "company_brain.agents.external_wiki.content_catalog_agent.write_wiki_page",
        lambda rel, title, body, **kw: store.write(
            rel, MarkdownDoc(frontmatter={"title": title, "section": kw.get("section")}, body=body)
        ),
    )

    result = ContentCatalogAgent(load_config()).run()
    assert result["status"] == "ok"
    assert result["path"] == "admin/table-of-contents.md"
