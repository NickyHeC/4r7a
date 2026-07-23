"""Weave Slack Events API router — @weave app_mention dispatch."""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.operations.slack import slack_client
from company_brain.config import AppConfig

MENTION_BODY_RE = re.compile(r"<@[^>]+>\s*(.*)", re.S)


class WeaveEventsRouter:
    """Route Weave app Events API payloads."""

    def __init__(self, config: AppConfig):
        self.config = config

    def handle_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = payload.get("type")
        if event_type == "url_verification":
            return {"challenge": payload.get("challenge")}

        if event_type != "event_callback":
            return {"status": "ignored", "reason": event_type or "unknown"}

        event = payload.get("event") or {}
        inner = str(event.get("type") or "")
        if inner == "app_mention":
            return self._handle_app_mention(event)
        return {"status": "ignored", "reason": inner or "unknown"}

    def _handle_app_mention(self, event: dict[str, Any]) -> dict[str, Any]:
        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
        user_id = str(event.get("user") or "")
        text = str(event.get("text") or "")
        if not channel_id or not user_id:
            return {"status": "skipped", "reason": "missing_target"}

        match = MENTION_BODY_RE.match(text.strip())
        query = (match.group(1) if match else text).strip()
        if not query:
            self._reply(channel_id, thread_ts, "Describe the system change after `@weave`.")
            return {"status": "skipped", "reason": "empty_query"}

        permalink = ""
        try:
            permalink = slack_client.permalink(channel_id, thread_ts, app="weave")
        except slack_client.SlackClientError:
            pass

        from company_brain.agents.admin.weave_triage import WeaveTriageAgent
        from company_brain.runtime import get_runtime

        result = get_runtime().run(
            WeaveTriageAgent,
            self.config,
            slack_user_id=user_id,
            text=query,
            channel_id=channel_id,
            thread_ts=thread_ts,
            permalink=permalink,
        )
        if result.get("status") == "rejected":
            self._reply(
                channel_id,
                thread_ts,
                "Weave is limited to active W2 members in `members.yaml` (roster cannot invoke).",
            )
        elif result.get("status") == "rate_limited":
            self._reply(channel_id, thread_ts, "Weave rate limit reached for today.")
        elif result.get("status") == "submitted":
            msg = (
                f"Recorded `{result.get('request_id')}` ({result.get('change_class')}). "
                f"Wiki: `{result.get('wiki_path')}`"
            )
            self._reply(channel_id, thread_ts, msg)
        return {"status": "weave_triage", "result": result}

    def _reply(self, channel_id: str, thread_ts: str, text: str) -> None:
        from company_brain.agents.operations.shared.operations_slack import reply_in_thread

        reply_in_thread(channel_id, thread_ts, text, app="weave")
