"""Admin Slack notifier for employee wiki import reviews."""

from __future__ import annotations

from company_brain.agents.employee_wiki.employee_wiki_config import import_config
from company_brain.agents.operations.shared.gmail_config import slack_cfg
from company_brain.agents.operations.shared.operations_slack import channel_notifier
from company_brain.notify import Notifier


def employee_wiki_admin_notifier() -> Notifier:
    cfg = import_config()
    channel = cfg.admin_channel or slack_cfg().get("ingest_channel") or "#ingest"
    return channel_notifier(channel)
