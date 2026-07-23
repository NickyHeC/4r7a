"""LinkedIn Pull — monthly public profile/posts → employee bio + voice.

Admin sets ``bindings.linkedin_url`` (members) or ``linkedin_url`` (roster) at
term start. Default search backend is ``lsearch`` via
``company_brain.web_search`` (``config/web_search.yaml``); falls back to Claude
Agent SDK ``WebSearch``. Cost-gated on content hash.

SDK: Anthropic Claude Agent SDK (format / WebSearch fallback). Search via
local-search when available.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, changed_since
from company_brain.config import AppConfig
from company_brain.members_config import load_members_config
from company_brain.roster_config import load_roster_config
from company_brain.wiki.employee_publish import APPEND, UPDATE, write_employee_wiki_page
from company_brain.wiki.employee_store import employee_wiki_store
from company_brain.wiki.publish import format_append_section

BIO_TITLE = "Bio"
VOICE_TITLE = "Voice"
_RESULT_START = "<<<HR_LINKEDIN>>>"
_RESULT_END = "<<<END_HR_LINKEDIN>>>"

STATE_PREFIX = "hr:linkedin:"
DUE_PREFIX = "hr:linkedin_due:"
WRITE_MODE = UPDATE
VOICE_WRITE_MODE = APPEND


class PullAgent(BaseAgent):
    """Pull public LinkedIn profile/posts into employee wiki."""

    name = "pull"
    max_iterations = 1
    WRITE_MODE = WRITE_MODE
    VOICE_WRITE_MODE = VOICE_WRITE_MODE

    def __init__(self, config: AppConfig, model: str | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self.model = model
        self._state = StateStore()

    def should_run(self, *, member_key: str = "", force: bool = False, **kwargs: Any) -> bool:
        """Cost gate: public-profile research runs at most monthly per scope."""
        if force:
            return True
        scope = (member_key or "all").strip()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._state.get(f"{DUE_PREFIX}{scope}") != month

    def run(
        self,
        *,
        member_key: str = "",
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if key:
            result = self._pull_one(key, force=force)
            if _pull_completed(result):
                self._mark_due(key)
            return result

        results: dict[str, Any] = {}
        for k, url in _active_linkedin_targets().items():
            results[k] = self._pull_one(k, force=force, linkedin_url=url)
        if not results:
            self._mark_due("all")
            return {"status": "ok", "reason": "no_targets", "members": {}}
        if all(_pull_completed(result) for result in results.values()):
            self._mark_due("all")
            return {"status": "ok", "members": results}
        return {
            "status": "error",
            "reason": "incomplete",
            "members": results,
        }

    def _mark_due(self, scope: str) -> None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        self._state.set(f"{DUE_PREFIX}{scope}", month)

    def _pull_one(
        self,
        member_key: str,
        *,
        force: bool = False,
        linkedin_url: str = "",
    ) -> dict[str, Any]:
        url = (linkedin_url or _linkedin_url_for(member_key) or "").strip()
        if not url:
            return {"status": "skipped", "reason": "no_linkedin_url", "member": member_key}

        try:
            raw, backend = asyncio.run(self._research_linkedin(member_key, url))
        except ImportError:
            self.logger.warning("claude-agent-sdk not installed — skip LinkedIn pull")
            return {"status": "skipped", "reason": "sdk_missing", "member": member_key}
        except Exception:
            self.logger.exception("LinkedIn research failed for %s", member_key)
            return {"status": "error", "reason": "search_failed", "member": member_key}

        if not raw.strip():
            return {"status": "skipped", "reason": "empty_search", "member": member_key}

        signature = hashlib.sha256(raw.encode()).hexdigest()[:32]
        state_key = f"{STATE_PREFIX}{member_key}"
        if not force and not changed_since(state_key, signature, store=self._state, update=False):
            return {"status": "skipped", "reason": "unchanged", "member": member_key}

        bio, posts = _parse_sections(raw)
        bio_path = f"{member_key}/bio.md"
        voice_path = f"{member_key}/voice.md"

        write_employee_wiki_page(
            bio_path,
            BIO_TITLE,
            bio or f"# Bio\n\n_No profile summary from LinkedIn search for `{url}`._\n",
            member=member_key,
            mode=self.WRITE_MODE,
            sync="private",
            sources=[url],
            mirror_notion=False,
        )

        voice_written = False
        store = employee_wiki_store()
        if not store.exists(voice_path):
            write_employee_wiki_page(
                voice_path,
                VOICE_TITLE,
                "# Voice\n\n_Public LinkedIn posts and writing samples._\n",
                member=member_key,
                mode=self.WRITE_MODE,
                sync="private",
                mirror_notion=False,
            )

        if posts.strip():
            stamp = datetime.now(timezone.utc).strftime("%Y-%m")
            section = format_append_section(
                f"LinkedIn posts — {stamp}",
                posts,
                trigger="hr_linkedin_pull",
                why=member_key,
            )
            write_employee_wiki_page(
                voice_path,
                VOICE_TITLE,
                section,
                member=member_key,
                mode=self.VOICE_WRITE_MODE,
                sync="private",
                sources=[url],
                mirror_notion=False,
            )
            voice_written = True

        self._state.set(state_key, signature)
        return {
            "status": "ok",
            "member": member_key,
            "bio_path": bio_path,
            "voice_written": voice_written,
            "signature": signature,
            "search_backend": backend,
        }

    async def _research_linkedin(self, member_key: str, url: str) -> tuple[str, str]:
        from company_brain import web_search as ws

        query = f"LinkedIn profile and recent public posts {url}"
        gathered = ws.gather_markdown(
            query,
            urls=[url],
            limit=5,
            with_content=True,
            cleanup=True,
        )
        if gathered.get("ok") and gathered.get("markdown"):
            formatted = await self._format_with_claude(
                member_key,
                url,
                context=str(gathered["markdown"]),
                allow_websearch=False,
            )
            return _extract_marked(formatted) or formatted, "lsearch"

        # Claude WebSearch fallback (portable / cloud hosts without Chromium)
        formatted = await self._format_with_claude(
            member_key,
            url,
            context="",
            allow_websearch=True,
        )
        return _extract_marked(formatted) or formatted, "claude"

    async def _format_with_claude(
        self,
        member_key: str,
        url: str,
        *,
        context: str,
        allow_websearch: bool,
    ) -> str:
        from claude_agent_sdk import ClaudeAgentOptions

        from company_brain.llm import claude as llm_claude
        from company_brain.llm.tracking import iter_claude_query

        if context:
            prompt = f"""You are writing an employee wiki bio from gathered public web data.

LinkedIn URL: {url}
Member key: {member_key}

GATHERED DATA:
{context}

Produce markdown between {_RESULT_START} and {_RESULT_END} with exactly two sections:

## Bio
A concise third-person bio (headline, current role, background). Wikipedia tone.
If nothing found, write one sentence saying the profile was not found.

## Posts
Bullet list of recent public posts or writing (date if known + short summary or quote).
If no posts found, write: (none)
"""
            tools: list[str] = []
        else:
            prompt = f"""You are researching a public LinkedIn profile for an employee wiki.

LinkedIn URL: {url}
Member key: {member_key}

Use web search to find publicly available information about this LinkedIn profile
and any recent public posts by this person.

Produce markdown between {_RESULT_START} and {_RESULT_END} with exactly two sections:

## Bio
A concise third-person bio (headline, current role, background). Wikipedia tone.
If nothing found, write one sentence saying the profile was not found in search.

## Posts
Bullet list of recent public posts or writing (date if known + short summary or quote).
If no posts found, write: (none)
"""
            tools = ["WebSearch"] if allow_websearch else []

        options = ClaudeAgentOptions(
            allowed_tools=tools,
            env=llm_claude.options_env(),
            **llm_claude.model_kwargs(self.model, agent_name="pull"),
        )
        out: list[str] = []
        async for message in iter_claude_query(
            "pull",
            prompt=prompt,
            options=options,
        ):
            result = getattr(message, "result", None)
            if isinstance(result, str):
                out.append(result)
        return "\n".join(out)


def _pull_completed(result: dict[str, Any]) -> bool:
    if result.get("status") == "ok":
        return True
    return result.get("status") == "skipped" and result.get("reason") in {
        "unchanged",
        "no_linkedin_url",
    }


def _extract_marked(raw: str) -> str:
    s, e = raw.rfind(_RESULT_START), raw.rfind(_RESULT_END)
    if s != -1 and e > s:
        return raw[s + len(_RESULT_START) : e].strip()
    return ""


def _parse_sections(raw: str) -> tuple[str, str]:
    text = raw.strip()
    bio_match = re.search(r"##\s*Bio\s*\n(.*?)(?=\n##\s*Posts|\Z)", text, re.S | re.I)
    posts_match = re.search(r"##\s*Posts\s*\n(.*)\Z", text, re.S | re.I)
    bio_body = (bio_match.group(1).strip() if bio_match else text).strip()
    posts_body = (posts_match.group(1).strip() if posts_match else "").strip()
    if posts_body.lower() in {"(none)", "none", "-", "n/a"}:
        posts_body = ""
    bio_doc = f"# Bio\n\n{bio_body}\n" if not bio_body.startswith("#") else bio_body
    return bio_doc, posts_body


def _linkedin_url_for(member_key: str) -> str:
    members = load_members_config()
    spec = members.get(member_key)
    if spec and spec.bindings.linkedin_url:
        return spec.bindings.linkedin_url
    roster = load_roster_config()
    person = roster.get(member_key)
    if person and person.linkedin_url:
        return person.linkedin_url
    return ""


def _active_linkedin_targets() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, spec in load_members_config().active_members().items():
        url = (spec.bindings.linkedin_url or "").strip()
        if url:
            out[key] = url
    for key, person in load_roster_config().people.items():
        if (person.status or "active").lower() != "active":
            continue
        url = (person.linkedin_url or "").strip()
        if url and key not in out:
            out[key] = url
    return out
