"""Ask Wiki — @wiki Q&A with channel ACL and Notion citations.

Humans only; internal channels. Connect channels are denied at the router.

SDK: OpenAI Agents SDK via ``oa.make_model()`` (provider-flexible).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack.rate_limits import (
    RateLimitExceeded,
    check_wiki_query_limit,
)
from company_brain.agents.operations.slack.wiki_acl import ask_wiki_allowed, search_wiki_snippets
from company_brain.config import AppConfig


class AskWikiAgent(BaseAgent):
    """Answer a wiki question scoped to the Slack channel ACL."""

    name = "ask_wiki"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)

    def run(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        query: str,
        slack_user_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not ask_wiki_allowed(channel_id):
            return self._reply(
                channel_id,
                thread_ts,
                "ask_wiki is not available in this channel (Connect or ACL).",
            )

        text = (query or "").strip()
        if not text:
            return self._reply(channel_id, thread_ts, "Ask a question after `@wiki`.")

        try:
            check_wiki_query_limit(slack_user_id)
        except RateLimitExceeded as exc:
            return self._reply(
                channel_id,
                thread_ts,
                f"Rate limit reached ({exc.limit}/{exc.window}). Try again later.",
            )

        try:
            from company_brain.agents.operations.slack.wiki_planner import plan_and_fetch

            snippets = plan_and_fetch(text, channel_id=channel_id)
        except Exception:
            self.logger.exception("wiki planner failed — falling back to single retrieve")
            snippets = search_wiki_snippets(text, channel_id=channel_id)
        if not snippets:
            return self._reply(
                channel_id,
                thread_ts,
                "I could not find matching wiki pages in this channel's scope.",
            )

        answer = self._compose_answer(text, snippets)
        try:
            from company_brain.wiki.who_knows import format_people_hints, suggest_people

            hints = suggest_people(text, limit=3)
            extra = format_people_hints(hints)
            if extra:
                answer = (answer or "").rstrip() + extra
        except Exception:
            self.logger.debug("who_knows hints skipped", exc_info=True)
        return self._reply(channel_id, thread_ts, answer)

    def _compose_answer(self, query: str, snippets: list[dict[str, Any]]) -> str:
        context_blocks = []
        for snip in snippets:
            cite = snip.get("notion_url") or snip.get("rel_path")
            context_blocks.append(
                f"### {snip['title']} ({snip['rel_path']})\n"
                f"Citation: {cite}\n\n"
                f"{snip['snippet'][:800]}"
            )
        context = "\n\n".join(context_blocks)

        try:
            from agents import Agent

            from company_brain.llm import openai_agents as oa
            from company_brain.llm.tracking import run_openai_sync

            prompt = f"""You answer questions using internal company wiki excerpts.
Cite sources with markdown links using the provided Citation URLs.
If the excerpts do not contain the answer, say you are unsure.

QUESTION:
{query}

WIKI EXCERPTS:
{context}

Reply in Slack mrkdwn (short, bullet-friendly). End with a "Sources:" list of links."""

            agent = Agent(
                name="ask_wiki",
                instructions="You answer internal wiki questions with citations.",
                model=oa.make_model(agent_name="ask_wiki"),
            )
            result = run_openai_sync(
                "ask_wiki",
                agent,
                prompt,
                run_config=oa.make_run_config(agent_name="ask_wiki"),
            )
            body = str(result.final_output or "").strip()
            if body:
                return body
        except Exception:
            self.logger.exception("ask_wiki LLM failed — using deterministic fallback")

        lines = [f"*Re: {query}*", ""]
        for snip in snippets[:3]:
            cite = snip.get("notion_url") or snip["rel_path"]
            lines.append(f"• <{cite}|{snip['title']}>")
        return "\n".join(lines)

    def _reply(self, channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
        try:
            ts = slack_client.post_thread_reply(channel_id, thread_ts, text)
            return {"status": "replied", "ts": ts}
        except slack_client.SlackClientError as exc:
            return {"status": "error", "reason": str(exc)}
