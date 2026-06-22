"""Extract plain text and metadata from Gmail REST message payloads."""

from __future__ import annotations

import base64
import re
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest


def plain_text(message: dict[str, Any], *, max_chars: int = 8000) -> str:
    parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime in ("text/plain", "text/html"):
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                raw = decoded.decode("utf-8", errors="replace")
                if mime == "text/html":
                    raw = re.sub(r"<[^>]+>", " ", raw)
                parts.append(raw)
            except (ValueError, UnicodeDecodeError):
                pass
        for child in part.get("parts") or []:
            walk(child)

    walk(message.get("payload") or {})
    text = "\n".join(parts).strip()
    if not text:
        text = rest.snippet(message)
    return text[:max_chars]


def question_count(text: str) -> int:
    return text.count("?")


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
