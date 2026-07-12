"""Bidirectional wiki ↔ Notion sync policy (signature gate + pull decisions).

MD remains the durable source of truth. Humans may edit Notion; agents reassert
only when their factual ``agent_signature`` changes. See ``docs/plans/notion.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from company_brain.wiki.store import compute_hash

# Department keys that fall back to the company teamspace when not split out.
COMPANY_FALLBACK_LOCATIONS = frozenset({"engineering", "product", "growth"})

HUMAN_OVERRIDE_NOTE_KEY = "human_override_note"
PRIOR_HUMAN_OVERRIDE_KEY = "prior_human_override"
AGENT_SIGNATURE_KEY = "agent_signature"
PUSHED_AGENT_SIGNATURE_KEY = "pushed_agent_signature"
AGENT_WRITTEN_AT_KEY = "agent_written_at"
SYNC_CONFLICT_KEY = "sync_conflict"


class SyncAction(str, Enum):
    NOOP = "noop"
    PULL = "pull"  # Notion → MD
    PUSH = "push"  # MD → Notion
    MERGE = "merge"  # write merged body to MD then push
    CONFLICT = "conflict"  # mark for Conflict Resolutions (Session 4)


@dataclass(frozen=True)
class SyncDecision:
    action: SyncAction
    merged_body: str | None = None
    reason: str = ""


def normalize_body(body: str) -> str:
    """Normalize markdown for equality / containment checks."""
    text = (body or "").replace("\r\n", "\n").strip()
    if text.startswith("# "):
        rest = text.split("\n", 1)
        text = rest[1].lstrip("\n") if len(rest) > 1 else ""
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Collapse runs of blank lines
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln.strip():
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def body_hash(body: str) -> str:
    return compute_hash(normalize_body(body))


def try_compatible_merge(md_body: str, notion_body: str) -> str | None:
    """Return a merged body when one side clearly contains the other; else None."""
    a = normalize_body(md_body)
    b = normalize_body(notion_body)
    if not a and b:
        return notion_body
    if not b and a:
        return md_body
    if a == b:
        return md_body
    if a in b:
        return notion_body
    if b in a:
        return md_body
    return None


def decide_pull_push(
    *,
    md_body: str,
    notion_body: str,
    synced_hash: str | None,
) -> SyncDecision:
    """Decide pull / push / merge / conflict for a bound page.

    ``synced_hash`` is the content hash recorded at the last successful mirror
    (normalized body hash preferred; legacy ``content_hash`` of raw body also works
    via equality on normalized forms when callers pass ``body_hash``).
    """
    md_h = body_hash(md_body)
    notion_h = body_hash(notion_body)

    if md_h == notion_h:
        return SyncDecision(SyncAction.NOOP, reason="bodies_equal")

    if not synced_hash:
        # No sync baseline — prefer Notion human surface when they differ, else push.
        merged = try_compatible_merge(md_body, notion_body)
        if merged is not None and body_hash(merged) == notion_h:
            return SyncDecision(SyncAction.PULL, reason="no_baseline_notion")
        if merged is not None and body_hash(merged) == md_h:
            return SyncDecision(SyncAction.PUSH, reason="no_baseline_md")
        if merged is not None:
            return SyncDecision(SyncAction.MERGE, merged_body=merged, reason="no_baseline_merge")
        return SyncDecision(SyncAction.CONFLICT, reason="no_baseline_diverge")

    md_synced = md_h == synced_hash
    notion_synced = notion_h == synced_hash

    if md_synced and not notion_synced:
        return SyncDecision(SyncAction.PULL, reason="notion_ahead")
    if notion_synced and not md_synced:
        return SyncDecision(SyncAction.PUSH, reason="md_ahead")
    if not md_synced and not notion_synced:
        merged = try_compatible_merge(md_body, notion_body)
        if merged is not None:
            return SyncDecision(SyncAction.MERGE, merged_body=merged, reason="both_changed_merge")
        return SyncDecision(SyncAction.CONFLICT, reason="both_changed")

    return SyncDecision(SyncAction.NOOP, reason="unexpected")


def should_skip_push_for_signature(
    *,
    agent_signature: str | None,
    pushed_agent_signature: str | None,
    md_body: str,
    notion_body: str | None,
) -> bool:
    """True when agent would re-push the same factual signature over a diverged Notion page."""
    if not agent_signature or not notion_body:
        return False
    if pushed_agent_signature != agent_signature:
        return False
    return body_hash(md_body) != body_hash(notion_body)


def stamp_human_override(fm: dict[str, Any], *, when_iso: str, detail: str) -> dict[str, Any]:
    """Record a short-horizon human win in frontmatter (not a Notion conflict row)."""
    out = dict(fm)
    out[HUMAN_OVERRIDE_NOTE_KEY] = detail
    out["human_override_at"] = when_iso
    out.pop(SYNC_CONFLICT_KEY, None)
    return out


def stamp_agent_push(fm: dict[str, Any], *, signature: str | None, when_iso: str) -> dict[str, Any]:
    """Mark a successful agent→Notion push; preserve prior human override as history."""
    out = dict(fm)
    if signature:
        out[PUSHED_AGENT_SIGNATURE_KEY] = signature
        out[AGENT_SIGNATURE_KEY] = signature
        out[AGENT_WRITTEN_AT_KEY] = when_iso
        note = out.pop(HUMAN_OVERRIDE_NOTE_KEY, None)
        if note:
            out[PRIOR_HUMAN_OVERRIDE_KEY] = note
        out.pop("human_override_at", None)
    out.pop(SYNC_CONFLICT_KEY, None)
    return out


def mark_sync_conflict(fm: dict[str, Any], *, reason: str) -> dict[str, Any]:
    out = dict(fm)
    out[SYNC_CONFLICT_KEY] = reason
    return out
