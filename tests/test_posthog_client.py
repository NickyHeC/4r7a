"""Unit tests for PostHog read-only client helpers (mocked HTTP)."""

from __future__ import annotations

import pytest

from company_brain.agents.product.posthog import posthog_client as client


def test_posthog_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in client._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("POSTHOG_HOST", raising=False)
    assert client.posthog_is_configured() is False
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    assert client.posthog_is_configured() is True
    assert client.project_id() == "42"
    assert client.host() == client.DEFAULT_HOST


def test_host_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_HOST", "https://eu.posthog.com/")
    assert client.host() == "https://eu.posthog.com"


def test_request_refuses_mutating_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    with pytest.raises(client.PostHogClientError, match="refuses method"):
        client._request("PATCH", "/api/projects/42/feature_flags/1/")
    with pytest.raises(client.PostHogClientError, match="only allows POST to /query"):
        client._request("POST", "/api/projects/42/feature_flags/")


def test_list_feature_flags_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")

    def fake_paginate(path: str, *, params: dict | None = None) -> list[dict]:
        assert "feature_flags" in path
        return [
            {"id": 1, "key": "export-csv", "name": "Export CSV", "active": True},
            {"id": 2, "key": "", "name": "bad"},
        ]

    monkeypatch.setattr(client, "_paginate", fake_paginate)
    rows = client.list_feature_flags()
    assert len(rows) == 1
    assert rows[0].key == "export-csv"
    assert rows[0].active is True


def test_list_event_definitions_and_experiments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")

    def fake_paginate(path: str, *, params: dict | None = None) -> list[dict]:
        if "event_definitions" in path:
            return [{"id": "a", "name": "user_signed_up"}]
        if "experiments" in path:
            return [
                {
                    "id": 9,
                    "name": "Checkout CTA",
                    "feature_flag": {"key": "checkout-cta"},
                    "start_date": "2026-01-01T00:00:00Z",
                    "end_date": None,
                    "archived": False,
                }
            ]
        return []

    monkeypatch.setattr(client, "_paginate", fake_paginate)
    events = client.list_event_definitions()
    assert events[0].name == "user_signed_up"
    exps = client.list_experiments()
    assert exps[0].feature_flag_key == "checkout-cta"
    assert exps[0].start_date == "2026-01-01"


def test_query_results_and_event_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")

    def fake_request(method: str, path: str, **kwargs):
        assert method == "POST"
        assert "/query/" in path
        return {"results": [["export_clicked", 12], ["other", 3]]}

    monkeypatch.setattr(client, "_request", fake_request)
    counts = client.event_counts(event_names=["export_clicked", "missing"], days=7)
    assert counts["export_clicked"] == 12
    assert counts["missing"] == 0


def test_has_events_since_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "42")
    monkeypatch.setattr(client, "query_results", lambda sql, **kw: [[5]])
    assert client.has_events_since_days(30) is True
    monkeypatch.setattr(client, "query_results", lambda sql, **kw: [[0]])
    assert client.has_events_since_days(30) is False
