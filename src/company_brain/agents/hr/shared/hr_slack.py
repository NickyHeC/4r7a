"""HR Notifier builders — admin departure asks and HR channel posts."""

from __future__ import annotations

from company_brain.agents.hr import hr_config as cfg
from company_brain.notify import Notifier


def hr_notifier() -> Notifier:
    """Notifier for HR admin asks. Prefers ``hr.slack.hr_channel``, else weave admin."""
    channel = cfg.hr_channel()
    if channel:
        from company_brain.agents.operations.shared.operations_slack import channel_notifier

        return channel_notifier(channel)
    from company_brain.agents.admin.weave_notify import weave_admin_notifier

    return weave_admin_notifier()
