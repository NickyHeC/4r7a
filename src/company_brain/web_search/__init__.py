"""Shared web search — default ``lsearch``, Claude WebSearch fallback.

Config: ``config/web_search.yaml``. Agents should gather via this package rather
than hardcoding Claude ``WebSearch`` tools.
"""

from __future__ import annotations

import logging
from typing import Any

from company_brain.web_search import lsearch as ls
from company_brain.web_search.config import configured_backend

logger = logging.getLogger(__name__)


def resolve_backend() -> str:
    """Return concrete backend: ``lsearch`` or ``claude``."""
    configured = configured_backend()
    if configured == "lsearch":
        return "lsearch" if ls.available() else "claude"
    if configured == "claude":
        return "claude"
    # auto
    return "lsearch" if ls.available() else "claude"


def search(
    query: str,
    *,
    limit: int | None = None,
    with_content: bool | None = None,
) -> ls.SearchResponse:
    """Run a web search on the resolved backend (lsearch only for structured hits)."""
    backend = resolve_backend()
    if backend == "lsearch":
        return ls.search(query, limit=limit, with_content=with_content)
    return ls.SearchResponse(
        ok=False,
        backend="claude",
        error="use_claude_websearch_tool",
    )


def read_url(url: str) -> ls.ReadResponse:
    if resolve_backend() != "lsearch":
        return ls.ReadResponse(ok=False, url=url, error="use_claude_websearch_tool")
    return ls.read_url(url)


def gather_markdown(
    query: str,
    *,
    urls: list[str] | None = None,
    limit: int | None = None,
    with_content: bool | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Collect search (+ optional URL reads) as markdown for LLM prompts.

    Returns ``{backend, ok, markdown, hits, reads}``. When backend is ``claude``,
    ``ok`` is False and callers should use the Claude WebSearch tool instead.
    """
    backend = resolve_backend()
    if backend != "lsearch":
        return {
            "backend": "claude",
            "ok": False,
            "markdown": "",
            "hits": [],
            "reads": [],
            "reason": "lsearch_unavailable",
        }

    try:
        resp = ls.search(query, limit=limit, with_content=with_content)
        hits = resp.hits if resp.ok else []
        reads: list[ls.ReadResponse] = []
        for url in urls or []:
            if not (url or "").strip():
                continue
            reads.append(ls.read_url(url.strip()))

        lines = [f"# Web search ({backend})", "", f"**Query:** {query}", ""]
        if hits:
            lines.append("## Results")
            lines.append("")
            for i, hit in enumerate(hits, 1):
                lines.append(f"{i}. **{hit.title or '(untitled)'}**")
                if hit.url:
                    lines.append(f"   - URL: {hit.url}")
                if hit.snippet:
                    lines.append(f"   - {hit.snippet}")
                if hit.content:
                    lines.append(f"   - Content: {hit.content[:800]}")
                lines.append("")
        else:
            lines.append("_No search hits._")
            lines.append("")

        if reads:
            lines.append("## Page reads")
            lines.append("")
            for r in reads:
                lines.append(f"### {r.url}")
                lines.append("")
                if r.ok and r.text:
                    lines.append(r.text[:4000])
                else:
                    lines.append(f"_Read failed: {r.error or 'empty'}_")
                lines.append("")

        return {
            "backend": "lsearch",
            "ok": bool(hits or any(r.ok for r in reads)),
            "markdown": "\n".join(lines).strip() + "\n",
            "hits": hits,
            "reads": reads,
            "error": resp.error if not resp.ok else "",
        }
    finally:
        if cleanup:
            ls.cleanup(kill=True)


async def claude_websearch_prompt(
    prompt: str,
    *,
    agent_name: str,
    model: str | None = None,
) -> str:
    """Run a Claude Agent SDK query with the ``WebSearch`` tool allowed."""
    from claude_agent_sdk import ClaudeAgentOptions

    from company_brain.llm import claude as llm_claude
    from company_brain.llm.tracking import iter_claude_query

    options = ClaudeAgentOptions(
        allowed_tools=["WebSearch"],
        env=llm_claude.options_env(),
        **llm_claude.model_kwargs(model, agent_name=agent_name),
    )
    out: list[str] = []
    async for message in iter_claude_query(agent_name, prompt=prompt, options=options):
        result = getattr(message, "result", None)
        if isinstance(result, str):
            out.append(result)
    return "\n".join(out)
