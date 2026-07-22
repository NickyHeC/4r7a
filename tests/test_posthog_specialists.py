"""Unit tests for PostHog specialist matchers, conclusive logic, and renderers."""

from __future__ import annotations

from datetime import datetime, timezone

from company_brain.agents.product.posthog.experiment_watch import (
    is_conclusive,
    render_experiment_watch,
    summarize_experiment,
)
from company_brain.agents.product.posthog.feature_match import (
    match_features,
    normalize_slug,
    parse_feature_titles,
)
from company_brain.agents.product.posthog.feature_usage import render_feature_usage
from company_brain.agents.product.posthog.signup_funnel import render_signup_funnel
from company_brain.agents.product.posthog.tracking_audit import render_tracking_audit


def test_parse_feature_titles_and_slug() -> None:
    body = """
# Product Features

## Detected 2026-07-20

- **feat: add export CSV** (`abc1234`, @nicky, 2026-07-20)
- **Add dark mode toggle** (`def5678`, @nicky, 2026-07-19)
- **feat: add export CSV** (`dup`, @nicky, 2026-07-18)
"""
    titles = parse_feature_titles(body)
    assert titles == ["feat: add export CSV", "Add dark mode toggle"]
    assert normalize_slug("feat: add export CSV") == "add-export-csv"


def test_match_features_matched_missing_orphan() -> None:
    rows, orphans = match_features(
        ["feat: add export CSV", "Mystery Feature"],
        ["export-csv", "unrelated-flag"],
        ["export_csv_clicked", "$pageview", "random_event"],
    )
    by_feature = {r.feature: r for r in rows}
    assert by_feature["feat: add export CSV"].status == "matched"
    assert "export-csv" in by_feature["feat: add export CSV"].flag_keys
    assert by_feature["Mystery Feature"].status == "missing"
    kinds = {(o.kind, o.key) for o in orphans}
    assert ("flag", "unrelated-flag") in kinds
    assert ("event", "random_event") in kinds
    assert ("event", "$pageview") not in kinds


def test_render_tracking_audit_tables() -> None:
    rows, orphans = match_features(
        ["Add export CSV"],
        ["export-csv"],
        ["export_csv"],
    )
    body = render_tracking_audit(
        rows, orphans, now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    )
    assert "matched" in body
    assert "`export-csv`" in body
    assert "Orphan" in body


def test_experiment_conclusive_by_probability() -> None:
    raw = {
        "id": 1,
        "name": "CTA",
        "metrics": [
            {"key": "control", "exposures": 200, "probability": 0.1},
            {"key": "test", "exposures": 200, "probability": 0.96},
        ],
    }
    assert is_conclusive(raw, min_exposures=100, probability_threshold=0.95) is True
    thin = {
        "metrics": [
            {"key": "control", "exposures": 10, "probability": 0.99},
            {"key": "test", "exposures": 10, "probability": 0.99},
        ]
    }
    assert is_conclusive(thin, min_exposures=100, probability_threshold=0.95) is False


def test_experiment_conclusive_by_significant_flag() -> None:
    raw = {
        "significant": True,
        "metrics": [
            {"key": "control", "exposures": 150, "probability": 0.4},
            {"key": "variant", "exposures": 150, "probability": 0.6, "significant": True},
        ],
    }
    summary = summarize_experiment(
        raw,
        name="X",
        flag_key="x",
        start_date="2026-01-01",
        end_date="",
        min_exposures=100,
        probability_threshold=0.95,
    )
    assert summary["conclusive"] is True
    assert summary["winner"] == "variant"


def test_render_experiment_watch() -> None:
    body = render_experiment_watch(
        [
            {
                "name": "CTA",
                "flag_key": "cta",
                "start_date": "2026-01-01",
                "end_date": "—",
                "winner": "test",
                "probability": 0.97,
                "conclusive": True,
                "reason": "p≥95%",
            }
        ],
        min_exposures=100,
        threshold=0.95,
        now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert "CTA" in body and "conclusive" in body


def test_render_feature_usage_and_funnel() -> None:
    usage = render_feature_usage(
        [
            {
                "feature": "Export CSV",
                "events": ["export_csv"],
                "flags": ["export-csv"],
                "l7d": 3,
                "l30d": 12,
            }
        ],
        unmatched=1,
        now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert "L7D" in usage and "12" in usage and "Skipped 1" in usage

    funnel = render_signup_funnel(
        short={
            "steps": [
                {"name": "Landing pageview", "event": "$pageview", "count": 100},
                {"name": "Create account", "event": "user_signed_up", "count": 10},
            ],
            "conversion_rate": 10.0,
        },
        long={
            "steps": [
                {"name": "Landing pageview", "event": "$pageview", "count": 400},
                {"name": "Create account", "event": "user_signed_up", "count": 40},
            ],
            "conversion_rate": 10.0,
        },
        short_days=7,
        long_days=30,
        source="config_fallback",
        insight_name="Landing to signup",
        dashboard_name="Signup",
        now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert "10.0%" in funnel
    assert "config defaults" in funnel
