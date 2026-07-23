"""Encyclopedia absorb urgency lanes (urgent → normal → bulk)."""

from __future__ import annotations

from typing import Any

from company_brain.config import load_yaml_config
from company_brain.ingestion.entry import RawEntry

LANE_ORDER = ("urgent", "normal", "bulk")
DEFAULT_TAG_LANES: dict[str, str] = {
    "urgent": "urgent",
    "admin_paste": "urgent",
    "knowledge_paste": "urgent",
    "security": "urgent",
    "normal": "normal",
    "slack": "normal",
    "thread": "normal",
    "encyclopedia": "normal",
    "bulk": "bulk",
    "notion_orphan": "bulk",
    "historical": "bulk",
}


def absorb_lane_config() -> dict[str, Any]:
    raw = load_yaml_config("wiki") or {}
    block = raw.get("absorb") or {}
    if not isinstance(block, dict):
        block = {}
    tag_lanes = dict(DEFAULT_TAG_LANES)
    custom = block.get("tag_lanes") or {}
    if isinstance(custom, dict):
        for k, v in custom.items():
            if str(v) in LANE_ORDER:
                tag_lanes[str(k)] = str(v)
    soft = block.get("encyclopedia_word_soft_cap") or [800, 1200]
    try:
        lo, hi = int(soft[0]), int(soft[1])
    except (TypeError, ValueError, IndexError):
        lo, hi = 800, 1200
    return {
        "tag_lanes": tag_lanes,
        "encyclopedia_word_soft_cap": (lo, hi),
        "soft_cap_guidance": bool(block.get("soft_cap_guidance", True)),
    }


def lane_for_entry(entry: RawEntry, *, tag_lanes: dict[str, str] | None = None) -> str:
    """Resolve lane from explicit metadata, then tags (urgent wins)."""
    meta = entry.metadata or {}
    explicit = str(meta.get("absorb_lane") or "").strip().lower()
    if explicit in LANE_ORDER:
        return explicit
    mapping = tag_lanes or absorb_lane_config()["tag_lanes"]
    found: set[str] = set()
    for tag in entry.tags or []:
        lane = mapping.get(str(tag).strip().lower())
        if lane in LANE_ORDER:
            found.add(lane)
    for lane in LANE_ORDER:
        if lane in found:
            return lane
    return "normal"


def sort_entries_by_lane(entries: list[RawEntry]) -> list[RawEntry]:
    cfg = absorb_lane_config()
    ranked = [
        (LANE_ORDER.index(lane_for_entry(e, tag_lanes=cfg["tag_lanes"])), e.timestamp, e)
        for e in entries
    ]
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in ranked]


def soft_cap_prompt_blurb() -> str:
    cfg = absorb_lane_config()
    if not cfg["soft_cap_guidance"]:
        return ""
    lo, hi = cfg["encyclopedia_word_soft_cap"]
    return (
        f"- Soft length target for encyclopedia-style articles: about {lo}–{hi} words. "
        "Stay near that range unless there is a clear reason to keep growing "
        "(e.g. a dense policy or ADR that must stay whole). Prefer split + "
        "[[wikilinks]] over cramming. Soft guidance only — do not invent a hard cutoff."
    )
