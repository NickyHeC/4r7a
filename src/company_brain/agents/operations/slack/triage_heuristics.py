"""Tier 0/1 Slack message triage heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from company_brain.agents.operations.slack import channels_config
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.action_items import message_has_action_item

MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")


@dataclass
class TriageResult:
    urgency: str  # immediate | deferred | skip
    kind: str | None = None
    attention: str | None = None
    assignees: list[str] = field(default_factory=list)
    customer: bool = False
    dispatch_action_items: bool = False
    reason: str = ""


def extract_mentions(text: str) -> list[str]:
    return MENTION_RE.findall(text or "")


def classify_tier0(
    message: dict[str, Any],
    *,
    channel_id: str,
    bot_user_id: str = "",
) -> TriageResult:
    if channels_config.is_out_of_scope(channel_id):
        return TriageResult(urgency="skip", reason="out_of_scope")

    subtype = str(message.get("subtype") or "")
    if subtype in {"bot_message", "message_changed", "message_deleted", "channel_join"}:
        return TriageResult(urgency="skip", reason=f"subtype:{subtype}")

    user = str(message.get("user") or "")
    if bot_user_id and user == bot_user_id:
        return TriageResult(urgency="skip", reason="bot_self")

    text = str(message.get("text") or "")
    if not text.strip():
        return TriageResult(urgency="skip", reason="empty")

    channel_meta = channels_config.get_channel(channel_id) or {}
    customer = bool(channel_meta.get("customer_support") or channel_meta.get("is_connect"))
    mentions = extract_mentions(text)
    human_mentions = [m for m in mentions if m != bot_user_id]

    if message_has_action_item(text):
        return TriageResult(
            urgency="immediate",
            kind="action_pending",
            attention=cfg.ATTENTION_ACTION,
            assignees=human_mentions,
            customer=customer,
            dispatch_action_items=True,
            reason="action_item",
        )

    if human_mentions:
        return TriageResult(
            urgency="immediate",
            kind="discussion_pending",
            attention=cfg.ATTENTION_REPLY,
            assignees=human_mentions,
            customer=customer,
            reason="mention",
        )

    if customer:
        return TriageResult(
            urgency="immediate",
            kind="discussion_pending",
            attention=cfg.ATTENTION_REPLY,
            customer=True,
            reason="customer_channel",
        )

    mode = channels_config.ingest_mode(channel_id)
    if mode == "cold":
        return TriageResult(
            urgency="deferred",
            kind="ingested",
            attention=cfg.ATTENTION_FYI,
            reason="cold_lane",
        )

    if "?" in text:
        return TriageResult(
            urgency="deferred",
            kind="discussion_pending",
            attention=cfg.ATTENTION_REPLY,
            reason="question",
        )

    return TriageResult(
        urgency="deferred",
        kind="ingested",
        attention=cfg.ATTENTION_FYI,
        reason="informational",
    )


def classify_tier1(messages: list[dict[str, Any]], *, channel_id: str) -> TriageResult:
    """Cheap batch pass over debounced messages (no LLM)."""
    if not messages:
        return TriageResult(urgency="skip", reason="empty_batch")

    best: TriageResult | None = None
    for msg in messages:
        result = classify_tier0(msg, channel_id=channel_id)
        if result.urgency == "skip":
            continue
        if best is None or _rank(result) > _rank(best):
            best = result
    return best or TriageResult(urgency="skip", reason="no_signal")


def _rank(result: TriageResult) -> int:
    order = {"immediate": 3, "deferred": 2, "skip": 1}
    return order.get(result.urgency, 0)
