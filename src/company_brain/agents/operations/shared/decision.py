"""Heuristics for sent-mail decision vs acknowledgment detection ($0)."""

from __future__ import annotations

import re
from typing import Any

from company_brain.agents.operations.shared.mail_body import plain_text, word_count

NON_DECISION_PATTERNS = (
    r"^thanks\b",
    r"^thank you\b",
    r"^got it\b",
    r"^sounds good\b",
    r"^perfect\b",
    r"^will do\b",
    r"^pass\b",
    r"^no thanks\b",
    r"^not interested\b",
    r"^received\b",
    r"^ack\b",
)

DECISION_HINTS = (
    "decided",
    "we will",
    "let's go with",
    "approved",
    "moving forward with",
    "confirmed",
    "agreed to",
    "final answer",
    "our decision",
    "we're going to",
)


def classify_sent_message(message: dict[str, Any]) -> str:
    """Return ``decision``, ``ingest``, or ``ack`` for a sent message."""
    text = plain_text(message, max_chars=4000).strip()
    lower = text.lower()
    normalized = re.sub(r"\s+", " ", lower).strip()

    if word_count(normalized) <= 12:
        for pat in NON_DECISION_PATTERNS:
            if re.search(pat, normalized):
                return "ack"

    if any(h in lower for h in DECISION_HINTS):
        return "decision"

    if word_count(normalized) >= 40:
        return "ingest"

    if word_count(normalized) <= 8:
        return "ack"

    return "ingest"
