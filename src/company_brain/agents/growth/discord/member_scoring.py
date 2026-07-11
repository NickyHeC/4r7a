"""Discord Member Scoring — monthly LLM batch on active community members.

SDK: OpenAI Agents SDK via ``oa.make_model()`` (provider-flexible).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.agents.growth.discord import discord_client
from company_brain.agents.growth.discord import discord_config as cfg
from company_brain.agents.growth.discord.routing import DiscordRoutingStore
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

MEMBER_DIR = "growth/discord/member"


class MemberScoringAgent(BaseAgent):
    """Score active Discord members and maintain member profile pages."""

    name = "discord_member_scoring"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._routing = DiscordRoutingStore()
        self._state = StateStore()

    def should_run(self, **kwargs: Any) -> bool:
        return discord_client.discord_is_configured()

    def run(self, **kwargs: Any) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        grouped = self._group_messages(since)
        scored = 0
        notified = 0
        min_messages = cfg.member_scoring_min_messages()
        threshold = cfg.interesting_score_threshold()

        for author_id, payload in grouped.items():
            if payload["count"] < min_messages:
                continue
            handle = payload["handle"] or author_id
            score, summary, use_case = self._score_member(handle, payload["messages"])
            self._write_member_page(author_id, handle, score, summary, use_case, payload["count"])
            scored += 1
            if score >= threshold and self._should_notify(author_id, score):
                if self._notify_member(handle, score, summary, use_case):
                    notified += 1

        return {"scored": scored, "notified": notified, "candidates": len(grouped)}

    def _group_messages(self, since: datetime) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"handle": "", "count": 0, "messages": []}
        )
        for record in self._routing.iter_all():
            updated = _parse_ts(record.updated_at)
            if updated and updated < since:
                continue
            extracted = record.extracted or {}
            author_id = str(extracted.get("author_id") or "")
            if not author_id:
                continue
            preview = str(extracted.get("text_preview") or "")
            if not preview.strip():
                continue
            bucket = grouped[author_id]
            bucket["handle"] = str(extracted.get("author_handle") or bucket["handle"])
            bucket["count"] += 1
            bucket["messages"].append(preview[:500])
        return grouped

    def _score_member(
        self,
        handle: str,
        messages: list[str],
    ) -> tuple[int, str, str]:
        joined = "\n---\n".join(messages[:12])
        try:
            from agents import Agent

            from company_brain.llm import openai_agents as oa
            from company_brain.llm.tracking import run_openai_sync

            prompt = f"""Score this open-source Discord community member for outreach value.

Member: {handle}
Recent messages:
{joined}

Reply in this exact format:
SCORE: <1-5 integer>
SUMMARY: <one sentence>
USE_CASE: <one sentence on how they may use the products, or "unknown">
"""
            agent = Agent(
                name="discord_member_scoring",
                instructions="You evaluate community members for product feedback potential.",
                model=oa.make_model(agent_name="discord_member_scoring"),
            )
            result = run_openai_sync(
                "discord_member_scoring",
                agent,
                prompt,
                run_config=oa.make_run_config(agent_name="discord_member_scoring"),
            )
            text = str(result.final_output or "")
            score = _parse_score(text)
            summary = _parse_field(text, "SUMMARY") or "Active community participant."
            use_case = _parse_field(text, "USE_CASE") or "unknown"
            return score, summary, use_case
        except Exception:
            self.logger.exception("Member scoring LLM failed for %s", handle)
            return min(3, 2 + len(messages) // 5), "Active community participant.", "unknown"

    def _write_member_page(
        self,
        author_id: str,
        handle: str,
        score: int,
        summary: str,
        use_case: str,
        message_count: int,
    ) -> None:
        slug = _member_slug(handle)
        rel_path = f"{MEMBER_DIR}/{slug}.md"
        body = "\n".join(
            [
                f"# {handle}",
                "",
                f"**Discord ID:** {author_id}",
                f"**Interesting score:** {score}/5",
                f"**Messages (30d):** {message_count}",
                "",
                "## Summary",
                "",
                summary,
                "",
                "## Possible use case",
                "",
                use_case,
                "",
            ]
        )
        write_wiki_page(
            rel_path,
            handle,
            body,
            mode=UPDATE,
            section="growth",
            type_="person",
            extra_frontmatter={
                "discord_id": author_id,
                "discord_handle": handle,
                "interesting_score": score,
                "last_scored_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _should_notify(self, author_id: str, score: int) -> bool:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        key = f"discord_member_alert:{author_id}:{month}"
        if self._state.get(key):
            return False
        self._state.set(key, {"score": score, "month": month})
        return True

    def _notify_member(self, handle: str, score: int, summary: str, use_case: str) -> bool:
        text = "\n".join(
            [
                "*Interesting Discord member*",
                f"*Handle:* {handle}",
                f"*Score:* {score}/5",
                f"*Summary:* {summary}",
                f"*Use case:* {use_case}",
            ]
        )
        return growth_notifier().emit(Signal(text=text, severity=ACTIONABLE))


def _member_slug(handle: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (handle or "unknown").lower()).strip("-")
    return slug[:48] or "unknown"


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_score(text: str) -> int:
    match = re.search(r"SCORE:\s*(\d)", text, re.I)
    if not match:
        return 3
    return max(1, min(5, int(match.group(1))))


def _parse_field(text: str, field: str) -> str:
    match = re.search(rf"{field}:\s*(.+)", text, re.I)
    return match.group(1).strip() if match else ""
