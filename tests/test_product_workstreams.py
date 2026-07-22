"""Tests for product workstreams (update, use_case, docs, progress, attribution)."""

from __future__ import annotations

from datetime import date, timedelta

from company_brain.agents.product.attribution.signup_match import (
    match_activity_to_signups,
    render_signup_match,
)
from company_brain.agents.product.attribution.signup_sources import SignupEvent
from company_brain.agents.product.docs.audit import render_docs_audit
from company_brain.agents.product.posthog.feature_usage import detect_usage_drops
from company_brain.agents.product.product_onboarding import (
    ProductOnboardingAgent,
    seed_workstream_pages,
)
from company_brain.agents.product.progress.compile import (
    compile_progress_rows,
    render_progress,
)
from company_brain.agents.product.shared import workstream_config as wcfg
from company_brain.agents.product.update.product_update import ProductUpdateAgent
from company_brain.agents.product.use_case.track import UseCaseTrackAgent
from company_brain.config import load_config
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


def _cfg():
    return load_config()


def test_workstream_config_loads():
    assert wcfg.update_poll_minutes() >= 60
    assert wcfg.attribution_poll_minutes() >= 30
    assert isinstance(wcfg.docs_proprietary_patterns(), list)
    assert "type" in wcfg.signup_source_cfg() or wcfg.signup_source_cfg() == {}


def test_product_onboarding_seeds_pages(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    seeded = seed_workstream_pages()
    assert "product/use-case/customer.md" in seeded
    assert "product/progress.md" in seeded
    store = LocalWikiStore(root=wiki)
    assert store.exists("product/use-case/adjacent.md")

    out = ProductOnboardingAgent(_cfg()).run(start_managers=False)
    assert out["status"] == "ok"
    assert out["managers_started"] == []
    # second seed is no-op
    assert seed_workstream_pages() == []


def test_detect_usage_drops():
    prior = {"Search": 100, "Tiny": 5, "Stable": 80}
    current = {"Search": 40, "Tiny": 1, "Stable": 75}
    drops = detect_usage_drops(current, prior_l7d=prior, drop_ratio=0.5, min_prior=20)
    assert len(drops) == 1
    assert drops[0]["feature"] == "Search"
    assert drops[0]["drop_pct"] == 60


def test_compile_progress_rows():
    features = ["Search", "Billing"]
    github = {
        "open_pr": "Working on Search filters",
        "branch_status": "",
        "feature_update": "Shipped Billing v2",
    }
    linear = [
        {"name": "Search", "done": 2, "total": 10, "ratio": 0.2, "status": "in_progress"},
        {"name": "Billing", "done": 9, "total": 10, "ratio": 0.9, "status": "shipping"},
    ]
    rows = compile_progress_rows(features, github=github, linear_projects=linear)
    by_f = {r["feature"]: r for r in rows}
    assert by_f["Search"]["status"] in {"in_progress", "shipping"}
    assert by_f["Billing"]["status"] in {"shipping", "shipped", "in_progress"}
    body = render_progress(rows, linear_projects=linear)
    assert "Product Progress" not in body  # title is in frontmatter/write path
    assert "Search" in body
    assert "Linear projects" in body


def test_product_update_draft(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))
    store = LocalWikiStore(root=wiki)
    store.write(
        "product/feature.md",
        MarkdownDoc(
            frontmatter={"title": "Product Features"},
            body="- **Fast Search** — find anything\n",
        ),
    )

    # suppress slack
    monkeypatch.setattr(
        "company_brain.agents.product.update.product_update.product_notifier",
        lambda: type("N", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    )
    monkeypatch.setattr(
        "company_brain.agents.product.update.product_update._try_llm_draft",
        lambda *a, **k: "",
    )

    out = ProductUpdateAgent(_cfg()).run(month="2026-07", force=True)
    assert out["status"] == "ok"
    assert store.exists("product/update/newsletter/2026-07.md")
    body = store.read("product/update/newsletter/2026-07.md").body
    assert "draft" in body.lower()
    assert "Fast Search" in body or "core product" in body.lower()


def test_use_case_track_template(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_STATE_PATH", str(tmp_path / "state.json"))

    monkeypatch.setattr(
        "company_brain.agents.product.use_case.track._gather",
        lambda q: "- Adjacent analytics for ops teams\n- Adjacent compliance packs\n",
    )
    out = UseCaseTrackAgent(_cfg()).run(force=True)
    assert out["status"] == "ok"
    assert out["added"] >= 1
    store = LocalWikiStore(root=wiki)
    assert store.exists("product/use-case/customer.md")
    assert store.exists("product/use-case/adjacent.md")


def test_docs_audit_render_and_proprietary():
    body = render_docs_audit(
        covered=["Search"],
        public_gaps=["Secret Internal Tool"],
        internal_only=["Secret Internal Tool"],
        fetch_notes=["docs.base_url unset — skipped live fetch."],
        base_url="",
    )
    assert "Intentionally internal" in body
    assert "Public gaps" in body


def test_signup_match_high_confidence():
    event_day = date.today() - timedelta(days=3)
    events = [{"slug": "demo-night", "title": "Demo Night", "date": event_day, "path": "x"}]
    signups = [
        SignupEvent(key=f"u{i}", when=event_day + timedelta(days=1), label=f"u{i}")
        for i in range(6)
    ]
    # sparse baseline before window
    for i in range(2):
        signups.append(
            SignupEvent(
                key=f"old{i}",
                when=event_day - timedelta(days=20 + i),
                label=f"old{i}",
            )
        )
    matches = match_activity_to_signups(events, signups, window_days=7, min_signups=3)
    assert matches
    assert matches[0]["confidence"] == "high"
    body = render_signup_match(matches, signup_count=len(signups), event_count=1)
    assert "Demo Night" in body
