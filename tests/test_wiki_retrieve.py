"""Tests for hybrid lexical wiki retrieval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from company_brain.wiki.retrieve import retrieve, score_document, tokenize
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _write(store: LocalWikiStore, rel: str, title: str, body: str, **fm) -> None:
    front = {"title": title, **fm}
    store.write(rel, MarkdownDoc(frontmatter=front, body=body))


def test_tokenize_min_len():
    assert "ab" not in tokenize("ab foo bar")
    assert tokenize("pending reviews") == ["pending", "reviews"]


def test_title_boost_ranks_title_match_higher(tmp_path: Path):
    store = LocalWikiStore(root=tmp_path)
    _write(
        store,
        "company/a.md",
        "Unrelated",
        "pending reviews appear many times pending reviews pending reviews",
    )
    _write(
        store,
        "company/b.md",
        "Pending Reviews",
        "short body about process",
    )
    hits = retrieve("pending reviews", store=store, prefixes=["company/"], limit=5)
    assert hits
    assert hits[0]["rel_path"] == "company/b.md"


def test_idf_prefers_rare_term(tmp_path: Path):
    store = LocalWikiStore(root=tmp_path)
    _write(store, "company/common.md", "Notes", "the word pending is everywhere pending")
    _write(
        store,
        "company/rare.md",
        "CKPT note",
        "set CKPT_PREFETCH for NFS restore stalls",
    )
    hits = retrieve("CKPT_PREFETCH restore", store=store, prefixes=["company/"], limit=5)
    assert hits
    assert hits[0]["rel_path"] == "company/rare.md"


def test_age_decay_prefers_recent(tmp_path: Path):
    store = LocalWikiStore(root=tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    _write(
        store,
        "company/old.md",
        "Restore hangs",
        "restore hangs after manifest load use legacy",
        updated=old,
    )
    _write(
        store,
        "company/new.md",
        "Restore hangs",
        "restore hangs after manifest load use prefetch",
        updated=new,
    )
    hits = retrieve("restore hangs manifest", store=store, prefixes=["company/"], limit=5)
    assert hits[0]["rel_path"] == "company/new.md"


def test_prefixes_filter(tmp_path: Path):
    store = LocalWikiStore(root=tmp_path)
    _write(store, "engineering/x.md", "Alpha", "unique_term_xyz")
    _write(store, "finance/y.md", "Alpha", "unique_term_xyz")
    hits = retrieve(
        "unique_term_xyz",
        store=store,
        prefixes=["engineering/"],
        deny_prefixes=("finance/",),
        limit=10,
    )
    assert all(h["rel_path"].startswith("engineering/") for h in hits)


def test_score_document_zero_without_terms():
    idf = {"foo": 1.0}
    assert score_document(["zzz"], title="a", body="b", idf=idf) == 0.0
