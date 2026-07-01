"""Tests for employee wiki zip import + duplicate detection (Phase D)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from company_brain.agents.employee_wiki.employee_wiki_import import EmployeeWikiImportAgent
from company_brain.config import load_config
from company_brain.wiki.duplicate_detect import detect_duplicates
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.import_promote import promote_import
from company_brain.wiki.import_scan import scan_import_files
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture
def wiki_roots(tmp_path: Path, monkeypatch):
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
    monkeypatch.setattr("company_brain.agents.gates.CONFIG_DIR", config_dir)
    (config_dir / "operations.yaml").write_text(
        "employee_wiki:\n  import:\n    require_admin_first_import: true\n"
    )
    return {"company": company, "employee": employee, "config": config_dir}


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_scan_blocks_secrets():
    report = scan_import_files({"notes/x.md": "key: sk-abcdefghijklmnopqrstuvwxyz1234567890\n"})
    assert not report.ok
    assert report.blocked()


def test_duplicate_exact_match_company(wiki_roots):
    company = LocalWikiStore(root=wiki_roots["company"])
    body = "# Acme spec\n\nBuild the integration.\n"
    company.write("projects/acme.md", MarkdownDoc(frontmatter={"title": "Acme spec"}, body=body))

    import_body = "---\ntitle: Acme spec\n---\n\n# Acme spec\n\nBuild the integration.\n"
    report = detect_duplicates(
        {"notes/acme-spec.md": import_body},
        member_key="alice",
        import_id="imp1",
        company_store=company,
        employee_store=LocalEmployeeWikiStore(),
    )
    assert report.files[0].verdict == "link"
    assert report.files[0].canonical == "projects/acme.md"
    assert report.files[0].match_tier == 1


def test_import_agent_quarantine_and_review(wiki_roots, monkeypatch):
    company = LocalWikiStore(root=wiki_roots["company"])
    company.write(
        "projects/acme.md",
        MarkdownDoc(
            frontmatter={"title": "Acme spec"},
            body="# Acme spec\n\nBuild the integration.\n",
        ),
    )

    zip_bytes = _make_zip(
        {
            "notes/acme-spec.md": "# Acme spec\n\nBuild the integration.\n",
            "notes/new-idea.md": "# New idea\n\nSomething fresh.\n",
        }
    )

    review_calls = []

    def fake_run(cls, config, **kwargs):
        review_calls.append(kwargs)
        return {"status": "ok", "review_page": "admin/import-review/x.md"}

    monkeypatch.setattr(
        "company_brain.agents.employee_wiki.employee_wiki_import.get_runtime",
        lambda: type("R", (), {"run": staticmethod(fake_run)})(),
    )

    agent = EmployeeWikiImportAgent(load_config())
    result = agent.run(member_key="alice", zip_bytes=zip_bytes)

    assert result["status"] == "pending_review"
    assert result["first_import"] is True
    store = LocalEmployeeWikiStore()
    q = result["quarantine"]
    assert store.exists(f"{q}notes/acme-spec.md")
    assert store.exists(f"{q}duplicate_report.json")
    dup = json.loads(store.read_text(f"{q}duplicate_report.json"))
    paths = {f["path"]: f for f in dup["files"]}
    assert paths["notes/acme-spec.md"]["verdict"] == "link"
    assert paths["notes/acme-spec.md"]["canonical"] == "projects/acme.md"
    assert review_calls


def test_promote_links_duplicate(wiki_roots):
    company = LocalWikiStore(root=wiki_roots["company"])
    company.write(
        "projects/acme.md",
        MarkdownDoc(
            frontmatter={"title": "Acme spec"},
            body="# Acme spec\n\nBuild the integration.\n",
        ),
    )
    employee = LocalEmployeeWikiStore()
    import_id = "imp99"
    q = f"alice/imports/_quarantine/{import_id}/"
    employee.write(
        f"{q}notes/acme-spec.md",
        MarkdownDoc(body="# Acme spec\n\nBuild the integration.\n"),
    )
    report = detect_duplicates(
        {"notes/acme-spec.md": employee.read(f"{q}notes/acme-spec.md").body},
        member_key="alice",
        import_id=import_id,
        company_store=company,
        employee_store=employee,
    )
    employee.write_text(f"{q}duplicate_report.json", report.serialize())

    result = promote_import("alice", import_id, store=employee)
    assert result.linked
    stub = result.linked[0]
    doc = employee.read(stub)
    assert doc.frontmatter.get("duplicate_of") == "projects/acme.md"
    assert not employee.exists(q.rstrip("/"))
