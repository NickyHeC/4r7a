"""Team On It Agent — delegate ``4. Team On It`` mail via Linear + Slack.

Creates a Linear issue for the team lead and posts a summary to the configured
Slack channel. Gmail literal forward is not used (send scope forbidden); the
team picks up work from Slack + Linear. Archive happens via Slack/Linear
completion, not inbox_sweep.

SDK: Neither (Linear GraphQL + Slack SDK).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.linear import linear_client
from company_brain.agents.operations.shared.gmail_config import mailbox_id
from company_brain.agents.operations.shared.linear_config import (
    default_priority,
    team_id,
    team_key,
    team_on_it_slack_channel,
)
from company_brain.agents.operations.shared.mail_body import plain_text
from company_brain.agents.operations.shared.operations_slack import OperationsSlack
from company_brain.agents.operations.shared.routing import RoutingStore
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Notifier, Signal

SPECIALIST_KEY = "team_on_it"


class TeamOnItAgent(BaseAgent):
    """Linear task + Slack handoff for Team On It attention mail."""

    name = "gmail_team_on_it"

    def __init__(self, config: AppConfig, mailbox: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.mailbox = mailbox or mailbox_id()
        self._store = RoutingStore()

    def should_run(self, **kwargs: Any) -> bool:
        return linear_client.linear_is_configured() and bool(
            self._store.unhandled_for(
                SPECIALIST_KEY, mailbox=self.mailbox, attention="4. Team On It",
            )
        )

    def run(self, **kwargs: Any) -> dict[str, Any]:
        handled = 0
        channel = team_on_it_slack_channel()
        slack = OperationsSlack(channel=channel)

        for record in self._store.unhandled_for(
            SPECIALIST_KEY, mailbox=self.mailbox, attention="4. Team On It",
        ):
            try:
                message = rest.get_message(record.message_id, mailbox=self.mailbox)
                subject = record.extracted.get("subject") or rest.message_subject_from(message)
                from_ = record.extracted.get("from") or rest.message_from(message)
                body = plain_text(message, max_chars=3000)
                description = (
                    f"Delegated from Gmail ({self.mailbox}).\n\n"
                    f"**From:** {from_}\n\n"
                    f"**Message:** `{record.message_id}`\n\n"
                    f"{body}"
                )
                issue = linear_client.create_issue(
                    title=f"[Team] {subject or 'Gmail delegation'}",
                    description=description,
                    team_id=team_id() or None,
                    team_key=team_key() or None,
                    priority=default_priority(),
                )
                ident = issue.get("identifier") or issue.get("id", "")
                url = issue.get("url", "")
                record.extracted["linear_issue_id"] = ident
                record.extracted["linear_issue_url"] = url
                self._store.write(record)

                text = (
                    f"*Team on it* — {subject}\n"
                    f"*From:* {from_}\n"
                    f"*Linear:* {ident}"
                )
                if url:
                    text += f"\n<{url}|Open in Linear>"
                Notifier(channel_post=slack.post).emit(Signal(text=text, severity=ACTIONABLE))

                self._store.mark_handled(record, SPECIALIST_KEY)
                handled += 1
            except Exception:
                self.logger.exception("team_on_it failed for %s", record.message_id)
        return {"handled": handled, "slack_channel": channel}
