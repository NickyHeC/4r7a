"""Segment long Slack threads into bursts before encyclopedia absorb enqueue.

Deterministic (no LLM): split by time gaps and speaker shifts; emit structured
bullets (question / decision / open) per burst.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_MIN_MESSAGES = 12
DEFAULT_GAP_SECONDS = 45 * 60  # 45 minutes


def burst_config() -> dict[str, int]:
    from company_brain.agents.operations.slack import slack_config as cfg

    raw = getattr(cfg, "thread_absorb_burst_min_messages", None)
    try:
        min_msgs = int(raw() if callable(raw) else (raw or DEFAULT_MIN_MESSAGES))
    except Exception:
        min_msgs = DEFAULT_MIN_MESSAGES
    return {"min_messages": max(3, min_msgs), "gap_seconds": DEFAULT_GAP_SECONDS}


def should_burst(messages: list[dict[str, Any]], *, min_messages: int | None = None) -> bool:
    threshold = min_messages if min_messages is not None else burst_config()["min_messages"]
    return len(messages or []) >= threshold


def segment_bursts(
    messages: list[dict[str, Any]],
    *,
    gap_seconds: int | None = None,
) -> list[list[dict[str, Any]]]:
    """Split messages into bursts by idle gap or speaker change after a gap."""
    if not messages:
        return []
    gap = gap_seconds if gap_seconds is not None else burst_config()["gap_seconds"]
    bursts: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    prev_ts: float | None = None
    prev_user: str | None = None
    for msg in messages:
        ts = _msg_ts(msg)
        user = str(msg.get("user") or msg.get("username") or "")
        if current and prev_ts is not None and ts is not None:
            idle = ts - prev_ts
            if idle >= gap or (
                idle >= gap / 3 and user and user != prev_user and len(current) >= 3
            ):
                bursts.append(current)
                current = []
        current.append(msg)
        if ts is not None:
            prev_ts = ts
        if user:
            prev_user = user
    if current:
        bursts.append(current)
    return bursts


def distill_bursts(messages: list[dict[str, Any]]) -> str:
    """Return markdown with per-burst structured bullets (or plain join if short)."""
    if not should_burst(messages):
        return _plain_transcript(messages)
    bursts = segment_bursts(messages)
    if len(bursts) <= 1:
        return _plain_transcript(messages)
    parts: list[str] = ["## Burst distill", ""]
    for i, burst in enumerate(bursts, 1):
        parts.append(f"### Burst {i}")
        parts.append("")
        for kind, text in _classify_burst(burst):
            parts.append(f"- **{kind}:** {text}")
        parts.append("")
        parts.append("<details><summary>Transcript</summary>")
        parts.append("")
        parts.append(_plain_transcript(burst))
        parts.append("")
        parts.append("</details>")
        parts.append("")
    return "\n".join(parts).strip()


def _classify_burst(burst: list[dict[str, Any]]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for msg in burst:
        text = str(msg.get("text") or "").strip()
        if not text:
            continue
        user = str(msg.get("user") or msg.get("username") or "unknown")
        lower = text.lower()
        if "?" in text or lower.startswith(("how ", "what ", "why ", "can we", "should we")):
            kind = "question"
        elif any(
            k in lower
            for k in ("decided", "we'll go with", "ship it", "approved", "final:", "going with")
        ):
            kind = "decision"
        elif any(k in lower for k in ("todo", "action:", "follow up", "open:", "still need")):
            kind = "open"
        else:
            kind = "note"
        rows.append((kind, f"{user}: {text[:400]}"))
    if not rows:
        rows.append(("note", "(empty burst)"))
    return rows


def _plain_transcript(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        user = str(msg.get("user") or msg.get("username") or "unknown")
        text = str(msg.get("text") or "").strip()
        if text:
            parts.append(f"**{user}:** {text}")
    return "\n\n".join(parts)


def _msg_ts(msg: dict[str, Any]) -> float | None:
    raw = msg.get("ts")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
