"""Heuristics for reply complexity ($0 gate before draft_reply LLM)."""

from __future__ import annotations

from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.mail_body import plain_text, question_count

COMPLEX_KEYWORDS = (
    "contract", "legal", "term sheet", "nda", "msa", "sow", "invoice dispute",
    "wire transfer", "lawsuit", "counsel", "signature required",
)


def is_simple_reply_message(message: dict[str, Any]) -> bool:
    """$0 gate on a single message before draft_reply invokes an LLM."""
    subject = rest.message_subject_from(message).lower()
    body = plain_text(message, max_chars=2000).lower()
    blob = f"{subject} {body}"
    if any(k in blob for k in COMPLEX_KEYWORDS):
        return False
    return question_count(body) <= 2


def is_simple_reply(thread: dict[str, Any], *, mailbox: str = "me") -> bool:
    """True when a thread looks safe for automated draft_reply."""
    messages = thread.get("messages") or []
    if len(messages) > 4:
        return False

    subjects = " ".join(rest.message_subject_from(m).lower() for m in messages)
    bodies = " ".join(plain_text(m, max_chars=2000).lower() for m in messages)
    blob = f"{subjects} {bodies}"

    if any(k in blob for k in COMPLEX_KEYWORDS):
        return False
    if question_count(bodies) > 2:
        return False

    senders = {rest.message_from(m).lower() for m in messages}
    if len(senders) > 3:
        return False

    return True
