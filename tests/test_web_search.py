"""Tests for company_brain.web_search (lsearch default + claude fallback)."""

from __future__ import annotations

import json
from pathlib import Path

from company_brain.web_search import gather_markdown, resolve_backend
from company_brain.web_search import lsearch as ls
from company_brain.web_search.lsearch import SearchHit, SearchResponse


def test_resolve_backend_auto_prefers_lsearch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("company_brain.web_search.config.CONFIG_DIR", tmp_path)
    (tmp_path / "web_search.yaml").write_text("backend: auto\n")
    monkeypatch.setattr(ls, "available", lambda: True)
    assert resolve_backend() == "lsearch"
    monkeypatch.setattr(ls, "available", lambda: False)
    assert resolve_backend() == "claude"


def test_resolve_backend_claude_forced(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("company_brain.web_search.config.CONFIG_DIR", tmp_path)
    (tmp_path / "web_search.yaml").write_text("backend: claude\n")
    monkeypatch.setattr(ls, "available", lambda: True)
    assert resolve_backend() == "claude"


def test_gather_markdown_formats_hits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("company_brain.web_search.config.CONFIG_DIR", tmp_path)
    (tmp_path / "web_search.yaml").write_text("backend: auto\nlsearch:\n  cleanup_after: false\n")
    monkeypatch.setattr(ls, "available", lambda: True)

    def _search(query, **kwargs):
        return SearchResponse(
            ok=True,
            hits=[
                SearchHit(
                    title="Example",
                    url="https://example.com",
                    snippet="hello",
                )
            ],
        )

    monkeypatch.setattr(ls, "search", _search)
    monkeypatch.setattr(ls, "cleanup", lambda **k: None)
    out = gather_markdown("example query", cleanup=False)
    assert out["ok"] is True
    assert out["backend"] == "lsearch"
    assert "Example" in out["markdown"]
    assert "https://example.com" in out["markdown"]


def test_lsearch_hits_from_payload() -> None:
    payload = {
        "ok": True,
        "results": [
            {"title": "A", "url": "https://a.test", "snippet": "s"},
        ],
    }
    hits = ls._hits_from_payload(payload)
    assert len(hits) == 1
    assert hits[0].title == "A"


def test_lsearch_parse_json_tolerant() -> None:
    raw = 'noise\n{"ok": true, "results": []}\n'
    assert ls._parse_json(raw).get("ok") is True
    assert ls._parse_json(json.dumps({"ok": True}))["ok"] is True
