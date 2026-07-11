"""Tier 0/1 Discord message triage heuristics for community ingest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from company_brain.agents.growth.discord import channels_config
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.operations.customer_support import (
    CustomerIntake,
    classify_customer_intake,
)

MENTION_RE = re.compile(r"<@!?\d+>")
URL_ONLY_RE = re.compile(r"^https?://\S+$", re.I)
SPAM_PATTERNS = (
    "free nitro",
    "discord.gg/",
    "click here",
    "dm me",
)


@dataclass
class TriageResult:
    urgency: str  # immediate | deferred | skip
    kind: str | None = None
    attention: str | None = None
    category: str | None = None  # bug | feature | discussion | technical
    reason: str = ""


def message_content(message: dict[str, Any]) -> str:
    return str(message.get("content") or "").strip()


def author_id(message: dict[str, Any]) -> str:
    author = message.get("author") or {}
    return str(author.get("id") or "")


def author_handle(message: dict[str, Any]) -> str:
    author = message.get("author") or {}
    return str(author.get("username") or author.get("global_name") or "")


def is_bot_message(message: dict[str, Any]) -> bool:
    author = message.get("author") or {}
    return bool(author.get("bot"))


def is_spam(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) < 2:
        return True
    if URL_ONLY_RE.match(lowered):
        return True
    if lowered.count("http") >= 3:
        return True
    return any(pat in lowered for pat in SPAM_PATTERNS)


def classify_intake_category(text: str) -> str:
    intake = CustomerIntake(source="discord", title=text[:120], body=text)
    return classify_customer_intake(intake)


def classify_tier0(
    message: dict[str, Any],
    *,
    channel_id: str,
    bot_user_id: str = "",
    channel_type: int | None = None,
) -> TriageResult:
    if channels_config.is_out_of_scope(channel_id):
        return TriageResult(urgency="skip", reason="out_of_scope")

    msg_type = int(message.get("type", 0))
    if msg_type not in {0, 19, 20}:
        return TriageResult(urgency="skip", reason=f"message_type:{msg_type}")

    if is_bot_message(message):
        return TriageResult(urgency="skip", reason="bot_message")

    user = author_id(message)
    if bot_user_id and user == bot_user_id:
        return TriageResult(urgency="skip", reason="bot_self")

    text = message_content(message)
    if not text:
        return TriageResult(urgency="skip", reason="empty")

    if is_spam(text):
        return TriageResult(urgency="skip", reason="spam")

    category = classify_intake_category(text)

    if category == "bug":
        return TriageResult(
            urgency="immediate",
            kind="bug_pending",
            attention=cfg.ATTENTION_ACTION,
            category="bug",
            reason="bug_signal",
        )

    if category == "feature":
        return TriageResult(
            urgency="immediate",
            kind="feature_pending",
            attention=cfg.ATTENTION_ACTION,
            category="feature",
            reason="feature_signal",
        )

    technical_signals = (
        "how do i",
        "how to",
        "configure",
        "config",
        "install",
        "setup",
        "api",
        "error",
        "exception",
        "stack trace",
    )
    lowered = text.lower()
    if "?" in text or any(sig in lowered for sig in technical_signals):
        return TriageResult(
            urgency="deferred",
            kind="technical_pending",
            attention=cfg.ATTENTION_REPLY,
            category="technical",
            reason="technical_question",
        )

    if MENTION_RE.search(text):
        return TriageResult(
            urgency="deferred",
            kind="discussion_pending",
            attention=cfg.ATTENTION_REPLY,
            category="discussion",
            reason="mention",
        )

    mode = channels_config.ingest_mode(channel_id)
    if mode == "cold":
        return TriageResult(
            urgency="deferred",
            kind="ingested",
            attention=cfg.ATTENTION_FYI,
            category="discussion",
            reason="cold_lane",
        )

    return TriageResult(
        urgency="deferred",
        kind="discussion_pending",
        attention=cfg.ATTENTION_FYI,
        category="discussion",
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
    base = order.get(result.urgency, 0)
    if result.category == "bug":
        return base + 3
    if result.category == "feature":
        return base + 2
    if result.category == "technical":
        return base + 1
    return base
