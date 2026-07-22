"""Use Case Track — web-search adjacent use cases (not customer duplicates).

SDK: web_search gather + optional Claude WebSearch; OpenAI Agents for normalize.
Customer use cases land via absorb into ``product/use-case/customer.md``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.shared.workstream_config import use_case_cfg
from company_brain.wiki.publish import (
    APPEND,
    UPDATE,
    format_append_section,
    read_wiki_page,
    write_wiki_page,
)
from company_brain.wiki.store import LocalWikiStore

CUSTOMER_PATH = "product/use-case/customer.md"
ADJACENT_PATH = "product/use-case/adjacent.md"
CUSTOMER_TITLE = "Customer Use Cases"
ADJACENT_TITLE = "Adjacent Use Cases"
FEATURE_WIKI = "product/feature.md"


class UseCaseTrackAgent(BaseAgent):
    """Discover adjacent use cases via web search; ensure customer page exists."""

    name = "use_case_track"
    WRITE_MODE = APPEND

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        _ensure_customer_seed()
        customer = read_wiki_page(CUSTOMER_PATH) or ""
        features = read_wiki_page(FEATURE_WIKI) or ""
        query = _build_query(customer=customer, features=features)
        gathered = _gather(query)
        ideas = _extract_ideas(gathered, customer=customer)
        if not ideas:
            return {
                "status": "ok",
                "added": 0,
                "wiki_path": ADJACENT_PATH,
                "query": query,
            }

        now = datetime.now(timezone.utc)
        section_body = "\n".join(f"- {idea}" for idea in ideas)
        section = format_append_section(
            f"Adjacent discoveries {now:%Y-%m-%d}",
            section_body,
            trigger="use_case_manager monthly",
            why=f"{len(ideas)} ideas from web search",
        )
        write_wiki_page(
            ADJACENT_PATH,
            ADJACENT_TITLE,
            section,
            mode=APPEND,
            section="product",
            type_="report",
        )
        return {
            "status": "ok",
            "added": len(ideas),
            "wiki_path": ADJACENT_PATH,
            "query": query,
        }


def _ensure_customer_seed() -> None:
    store = LocalWikiStore()
    if store.exists(CUSTOMER_PATH):
        return
    write_wiki_page(
        CUSTOMER_PATH,
        CUSTOMER_TITLE,
        "# Customer Use Cases\n\n"
        "How customers use the product. Absorb and humans land use-case content here.\n",
        mode=UPDATE,
        section="product",
        sync=False,
    )


def _build_query(*, customer: str, features: str) -> str:
    suffix = str(use_case_cfg().get("query_suffix") or "product use cases").strip()
    tokens: list[str] = []
    for line in (features + "\n" + customer).splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        clean = re.sub(r"^[-*]\s+", "", line)
        if len(clean) > 8:
            tokens.append(clean[:80])
        if len(tokens) >= 5:
            break
    seed = " ".join(tokens[:3]) if tokens else "SaaS"
    return f"{seed} {suffix}".strip()


def _gather(query: str) -> str:
    from company_brain import web_search

    result = web_search.gather_markdown(query, limit=8)
    if result.get("ok") and result.get("markdown"):
        return str(result["markdown"])
    try:
        return asyncio.run(
            web_search.claude_websearch_prompt(
                f"List 5 adjacent product use cases (not duplicates) for: {query}. "
                "Return markdown bullet list only.",
                agent_name="use_case_track",
            )
        )
    except Exception:
        return ""


def _extract_ideas(markdown: str, *, customer: str, limit: int = 5) -> list[str]:
    customer_l = customer.lower()
    ideas: list[str] = []
    for line in (markdown or "").splitlines():
        m = re.match(r"^[-*\d.)\s]+(.+)$", line.strip())
        if not m:
            continue
        idea = m.group(1).strip()
        if len(idea) < 12:
            continue
        if idea.lower() in customer_l:
            continue
        if any(idea.lower() == i.lower() for i in ideas):
            continue
        ideas.append(idea[:240])
        if len(ideas) >= limit:
            break
    return ideas
