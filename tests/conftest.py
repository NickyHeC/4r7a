"""Shared test fixtures.

Guards tracked config files from being mutated by unit tests. Agents such as
``ingest_triage`` call ``channels_config.upsert_channel`` as a side effect, which
writes to the real ``config/slack_channels.json``. Redirect that path to a
per-test temp file so the source-of-truth registry stays clean.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_slack_channels_registry(tmp_path, monkeypatch):
    from company_brain.agents.operations.slack import channels_config

    monkeypatch.setattr(
        channels_config,
        "CHANNELS_FILE",
        tmp_path / "slack_channels.json",
    )
