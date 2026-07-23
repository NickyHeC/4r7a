"""who_knows — derived expertise index from people / Slack / Granola.

Rebuild writes ``people/_who-knows.md``. Suggestions are hints only (no DMs).
Connect channels are excluded from Slack evidence.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from company_brain.config import resolve_wiki_dir
from company_brain.members_config import load_members_config
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, WikiStore

logger = logging.getLogger(__name__)

INDEX_PATH = "people/_who-knows.md"
INDEX_TITLE = "Who Knows"
INDEX_JSON = "people/_who-knows.json"
DEFAULT_MIN_SCORE = 2.0


def who_knows_config() -> dict[str, Any]:
    from company_brain.config import load_yaml_config

    raw = load_yaml_config("operations") or {}
    block = (raw.get("who_knows") or {}) if isinstance(raw, dict) else {}
    return block if isinstance(block, dict) else {}


def min_score() -> float:
    try:
        return float(who_knows_config().get("min_score") or DEFAULT_MIN_SCORE)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SCORE


def rebuild_who_knows_index(
    *,
    store: WikiStore | None = None,
    sync: bool = False,
) -> dict[str, Any]:
    """Scan people pages, Slack routing (non-connect), Granola meetings → index."""
    store = store or LocalWikiStore(root=resolve_wiki_dir())
    scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # member -> topic -> score

    _score_people_pages(store, scores)
    _score_slack_routing(scores)
    _score_granola(store, scores)

    members = load_members_config()
    rows: list[dict[str, Any]] = []
    for member_key, topics in scores.items():
        if member_key not in members.members and not member_key:
            continue
        ranked = sorted(topics.items(), key=lambda kv: kv[1], reverse=True)
        top = [(t, s) for t, s in ranked if s >= min_score()][:12]
        if not top:
            continue
        spec = members.get(member_key)
        name = member_key
        if spec and spec.email:
            name = spec.email.split("@")[0]
        rows.append(
            {
                "member": member_key,
                "name": name,
                "topics": [{"topic": t, "score": round(s, 2)} for t, s in top],
            }
        )
    rows.sort(key=lambda r: r["member"])

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "min_score": min_score(),
        "people": rows,
    }
    store.write_text(INDEX_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    body_lines = [
        f"# {INDEX_TITLE}",
        "",
        "Derived expertise hints (Slack / people / Granola). Connect channels excluded. "
        "No DMs — suggestions only.",
        "",
        f"_Updated: {payload['updated_at'][:10]}_ · min score `{payload['min_score']}`",
        "",
        "| Member | Topics |",
        "|--------|--------|",
    ]
    for row in rows:
        topics = ", ".join(f"{t['topic']} ({t['score']})" for t in row["topics"][:6])
        body_lines.append(f"| [[{row['member']}]] | {topics} |")
    body_lines.append("")
    write_wiki_page(
        INDEX_PATH,
        INDEX_TITLE,
        "\n".join(body_lines),
        mode=UPDATE,
        section="people",
        sync_label="admin_only",
        store=store,
        sync=sync,
        type_="index",
    )
    return {"status": "ok", "people": len(rows), "path": INDEX_PATH}


def load_who_knows_index(*, store: WikiStore | None = None) -> dict[str, Any]:
    store = store or LocalWikiStore(root=resolve_wiki_dir())
    if not store.exists(INDEX_JSON):
        return {"people": []}
    try:
        return json.loads(store.read_text(INDEX_JSON))
    except (OSError, json.JSONDecodeError):
        return {"people": []}


def suggest_people(
    query: str,
    *,
    limit: int = 3,
    store: WikiStore | None = None,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Return people hints for a query (fail closed to empty)."""
    index = load_who_knows_index(store=store)
    terms = {t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3}
    if not terms:
        return []
    thresh = threshold if threshold is not None else min_score()
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in index.get("people") or []:
        best = 0.0
        matched: list[str] = []
        for topic_row in row.get("topics") or []:
            topic = str(topic_row.get("topic") or "").lower()
            score = float(topic_row.get("score") or 0)
            if score < thresh:
                continue
            topic_terms = set(re.split(r"\W+", topic))
            overlap = terms & topic_terms
            if overlap:
                hit = score * (1 + 0.5 * len(overlap))
                if hit > best:
                    best = hit
                    matched = sorted(overlap)
        if best > 0:
            scored.append(
                (
                    best,
                    {
                        "member": row.get("member"),
                        "name": row.get("name") or row.get("member"),
                        "score": round(best, 2),
                        "reason": f"topics matching {', '.join(matched)}",
                        "people_path": f"people/{row.get('member')}.md",
                    },
                )
            )
    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:limit]]


def format_people_hints(hints: list[dict[str, Any]]) -> str:
    if not hints:
        return ""
    lines = ["", "*People who may know:*"]
    for h in hints:
        name = h.get("name") or h.get("member")
        reason = h.get("reason") or ""
        path = h.get("people_path") or ""
        if path:
            lines.append(f"• {name} (`{path}`) — {reason}")
        else:
            lines.append(f"• {name} — {reason}")
    return "\n".join(lines)


def _score_people_pages(store: WikiStore, scores: dict[str, dict[str, float]]) -> None:
    for rel in store.list():
        if not rel.startswith("people/") or not rel.endswith(".md"):
            continue
        if rel.startswith("people/_"):
            continue
        member = rel.removeprefix("people/").removesuffix(".md")
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        text = f"{doc.frontmatter.get('title', '')} {doc.body}".lower()
        for term in _topic_terms(text):
            scores[member][term] += 1.5


def _score_slack_routing(scores: dict[str, dict[str, float]]) -> None:
    try:
        from company_brain.agents.operations.slack import channels_config
    except Exception:
        return
    members = load_members_config()
    records = _iter_slack_routing_files()
    for record in records:
        channel = str(record.get("channel") or "")
        if not channel:
            continue
        try:
            if channels_config.is_connect_channel(channel):
                continue
        except Exception:
            continue
        extracted = record.get("extracted") or {}
        participants = extracted.get("participants") or []
        text = " ".join(
            str(x)
            for x in (
                extracted.get("text_preview"),
                extracted.get("title_preview"),
                extracted.get("kind"),
            )
            if x
        ).lower()
        topics = _topic_terms(text)
        if not topics:
            continue
        for user in participants:
            member = members.find_by_slack_user_id(str(user))
            if not member:
                continue
            for t in topics:
                scores[member][t] += 1.0


def _score_granola(store: WikiStore, scores: dict[str, dict[str, float]]) -> None:
    members = load_members_config()
    for rel in store.list():
        if not rel.startswith("operations/granola/meeting/") or not rel.endswith(".md"):
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        fm = doc.frontmatter or {}
        attendees = fm.get("attendees") or fm.get("participants") or []
        if isinstance(attendees, str):
            attendees = [attendees]
        text = f"{fm.get('title', '')} {doc.body[:2000]}".lower()
        topics = _topic_terms(text)
        for att in attendees:
            label = str(att).strip()
            member = members.find_by_granola_label(label) or _member_from_name(label, members)
            if not member:
                continue
            for t in topics:
                scores[member][t] += 1.2


def _iter_slack_routing_files() -> list[dict[str, Any]]:
    root = resolve_wiki_dir() / "operations" / "slack" / "routing"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in root.rglob("*.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _topic_terms(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "your",
        "about",
        "into",
        "was",
        "are",
        "will",
        "just",
        "not",
    }
    terms = []
    for t in re.split(r"\W+", text.lower()):
        if len(t) < 4 or t in stop:
            continue
        terms.append(t)
    # Unique preserve order, cap
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 20:
            break
    return out


def _member_from_name(label: str, members) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if slug in members.members:
        return slug
    return None


__all__ = [
    "INDEX_PATH",
    "format_people_hints",
    "load_who_knows_index",
    "rebuild_who_knows_index",
    "suggest_people",
]
