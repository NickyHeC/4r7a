"""Notification layer: detect everything, notify selectively.

Ramp's lesson: watch every signal, but every message that reaches a human must
mean something - "teams ignore noisy monitors, and they'll ignore noisy agents
too." Agents emit ``Signal`` objects; the ``Notifier`` decides what actually
reaches Slack/Notion based on severity and triage.

Severity:
- ``info``       — routine; suppressed by default (logged only).
- ``actionable`` — a human should look; delivered.
- ``alert``      — failure/urgent; always delivered.

A ``Signal`` may also be explicitly ``silent`` ([SILENT]) to suppress delivery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

INFO = "info"
ACTIONABLE = "actionable"
ALERT = "alert"

_DELIVERED = {ACTIONABLE, ALERT}


@dataclass
class Signal:
    text: str
    severity: str = INFO
    link_label: str | None = None
    link_url: str | None = None
    silent: bool = False


class Notifier:
    """Routes signals to a channel only when they are worth a human's attention."""

    def __init__(self, channel_post=None):
        # channel_post(text) -> Any; injected so this stays decoupled from Slack.
        self._post = channel_post

    def should_deliver(self, signal: Signal) -> bool:
        if signal.silent:
            return False
        return signal.severity in _DELIVERED

    def emit(self, signal: Signal) -> bool:
        """Emit a signal. Returns True if it was delivered, False if suppressed."""
        if not self.should_deliver(signal):
            logger.info("[suppressed:%s] %s", signal.severity, signal.text)
            return False
        text = signal.text
        if signal.link_url:
            label = signal.link_label or "link"
            text = f"{text}\n<{signal.link_url}|{label}>"
        if self._post:
            self._post(text)
        else:
            logger.info("[notify] %s", text)
        return True


def from_finance_config(finance_config: dict[str, Any] | None) -> Notifier:
    """Build a Notifier that posts to the finance Slack channel."""
    from company_brain.agents.finance.shared.slack import from_config as slack_from_config

    slack = slack_from_config(finance_config)
    return Notifier(channel_post=slack.post)
