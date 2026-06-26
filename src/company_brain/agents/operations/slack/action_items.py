"""Slack action-item heuristics shared by watcher and specialist."""

from __future__ import annotations

import re

from company_brain.agents.operations.slack import slack_config as cfg

CHECKBOX_RE = re.compile(r"^[\s>*\-]*\(?\[?[ xX]?\]?\)?[\s]*(.+)$")


def message_has_action_item(text: str) -> bool:
    lower = (text or "").lower()
    if not lower.strip():
        return False
    if any(kw in lower for kw in cfg.action_keywords()):
        return True
    if re.search(r"^-\s*\[[ xX]\]", text.strip(), re.M):
        return True
    return False


def extract_action_title(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in lines:
        if message_has_action_item(line):
            m = CHECKBOX_RE.match(line)
            body = (m.group(1) if m else line).strip()
            body = re.sub(r"^action items?:\s*", "", body, flags=re.I)
            body = re.sub(r"^todo:\s*", "", body, flags=re.I)
            if len(body) >= 4:
                return body[:200]
    compact = " ".join(lines)
    return compact[:200] if compact else "Slack action item"
