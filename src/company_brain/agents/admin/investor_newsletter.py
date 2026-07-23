"""Investor newsletter — concise monthly draft for admin audience (never sends).

SDK: OpenAI Agents SDK when available; template fallback.
Pulls cross-wiki evidence; prefers GitHub wiki pages over live gh.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

NEWSLETTER_DIR = "admin/investor-newsletter"
PROGRESS_WIKI = "product/progress.md"
FEATURE_WIKI = "product/feature.md"
FEATURE_UPDATE = "engineering/github/feature-update.md"
OPEN_PR = "engineering/github/open-pr.md"
BRANCH_STATUS = "engineering/github/branch-status.md"
QUARTERLY = "finance/quarterly-metric.md"
SIGNUP = "product/posthog/signup-funnel.md"
USAGE = "product/posthog/feature-usage.md"
WRITE_MODE = UPDATE
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MAX_WORDS = 800


class InvestorNewsletterAgent(BaseAgent):
    """Draft a short monthly investor update (admin_only wiki; never send)."""

    name = "investor_newsletter"
    WRITE_MODE = WRITE_MODE

    def should_run(self, *, month: str | None = None, force: bool = False, **kwargs: Any) -> bool:
        """Cost gate: do not invoke the writer when this month's draft exists."""
        if force:
            return True
        month_key = month or datetime.now(timezone.utc).strftime("%Y-%m")
        return not LocalWikiStore().exists(f"{NEWSLETTER_DIR}/{month_key}.md")

    def run(
        self,
        *,
        month: str | None = None,
        force: bool = False,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        month_key = month or now.strftime("%Y-%m")
        rel = f"{NEWSLETTER_DIR}/{month_key}.md"
        store = LocalWikiStore()
        if store.exists(rel) and not force:
            return {"status": "exists", "wiki_path": rel, "notify": False}

        evidence = gather_investor_evidence(month_key)
        body = _draft_body(month_key, evidence)
        title = f"Investor Update {month_key}"
        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="admin",
            type_="draft",
            sources=evidence.get("sources") or [],
            extra_frontmatter={
                "status": "draft",
                "month": month_key,
                "channel": "investor",
                "sync": "admin_only",
            },
            sync=sync,
        )
        wiki_admin_notifier().emit(
            Signal(
                text=(
                    f"Investor newsletter draft ready for {month_key} (`{rel}`). "
                    "Review and send manually — agent never sends."
                ),
                severity=ACTIONABLE,
            )
        )
        return {
            "status": "ok",
            "wiki_path": rel,
            "sources": evidence.get("sources") or [],
            "notify": True,
        }

    def verify(self, output: Any, **kwargs: Any) -> Any:
        from company_brain.agents.result import AgentResult

        if not isinstance(output, dict):
            return AgentResult(output=output, status="rework", gaps=["expected dict output"])
        if output.get("status") == "exists":
            return AgentResult(output=output, status="ok")
        rel = str(output.get("wiki_path") or "")
        body = read_wiki_page(rel) or ""
        if "draft" not in body.lower():
            return AgentResult(output=output, status="rework", gaps=["missing draft marker"])
        if not (output.get("sources") or []):
            return AgentResult(output=output, status="rework", gaps=["no sources"])
        words = len(re.findall(r"\b\w+\b", body))
        if words > MAX_WORDS:
            return AgentResult(output=output, status="rework", gaps=[f"too long ({words} words)"])
        if EMAIL_RE.search(body):
            return AgentResult(output=output, status="rework", gaps=["email address detected"])
        return AgentResult(output=output, status="ok")


def gather_investor_evidence(month_key: str) -> dict[str, Any]:
    sources: list[str] = []
    chunks: dict[str, str] = {}

    def take(path: str, key: str) -> None:
        text = read_wiki_page(path) or ""
        if text.strip():
            chunks[key] = text
            sources.append(path)

    take(PROGRESS_WIKI, "progress")
    take(FEATURE_WIKI, "features")
    take(FEATURE_UPDATE, "feature_update")
    take(OPEN_PR, "open_pr")
    take(BRANCH_STATUS, "branch_status")
    take(QUARTERLY, "quarterly")
    take(SIGNUP, "signup")
    take(USAGE, "usage")

    # Prefer wiki feature-update; live gh only if slice looks empty for the month
    if "feature_update" not in chunks or month_key not in chunks.get("feature_update", ""):
        gh_note = _gh_month_fallback(month_key)
        if gh_note:
            chunks["gh_commits"] = gh_note
            sources.append("github:commits")

    prior = read_wiki_page(f"{NEWSLETTER_DIR}/{_prior_month_key(month_key)}.md") or ""
    if prior.strip():
        chunks["prior"] = prior
        sources.append(f"{NEWSLETTER_DIR}/{_prior_month_key(month_key)}.md")

    return {"month": month_key, "chunks": chunks, "sources": sources}


def _prior_month_key(month_key: str) -> str:
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _gh_month_fallback(month_key: str) -> str:
    try:
        from company_brain.agents.engineering.github import gh as gh_api

        since = f"{month_key}-01"
        if hasattr(gh_api, "list_recent_commits"):
            commits = gh_api.list_recent_commits(since=since) or []
            lines = []
            for c in commits[:12]:
                if isinstance(c, dict):
                    lines.append(f"- {c.get('message') or c.get('sha') or c}")
                else:
                    lines.append(f"- {c}")
            return "\n".join(lines)
    except Exception:
        return ""
    return ""


def _bullets_from(md: str, *, limit: int = 6) -> list[str]:
    bullets: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^[-*]\s+(.+)$", line.strip())
        if m:
            bullets.append(m.group(1).strip())
        if len(bullets) >= limit:
            break
    return bullets


def _draft_body(month_key: str, evidence: dict[str, Any]) -> str:
    chunks: dict[str, str] = evidence.get("chunks") or {}
    drafted = _try_llm_draft(month_key, chunks)
    if drafted:
        return "\n".join(
            [
                f"# Investor Update {month_key}",
                "",
                drafted.strip(),
                "",
                "---",
                "",
                "_Status: draft — never sent by company-brain._",
                "",
            ]
        )

    product = _bullets_from(chunks.get("progress") or chunks.get("features") or "")
    eng = _bullets_from(chunks.get("feature_update") or chunks.get("gh_commits") or "")
    traction = _bullets_from(chunks.get("signup") or chunks.get("usage") or "", limit=3)
    business = _bullets_from(chunks.get("quarterly") or "", limit=3)
    ahead = _bullets_from(chunks.get("open_pr") or chunks.get("branch_status") or "", limit=3)

    lines = [
        f"# Investor Update {month_key}",
        "",
        f"Quick pulse for {month_key} across product, engineering, and the business.",
        "",
        "## Product",
        "",
    ]
    lines.extend(f"- {b}" for b in (product or ["_(no product wiki signal this month)_"]))
    lines.extend(["", "## Engineering", ""])
    lines.extend(f"- {b}" for b in (eng or ["_(no engineering wiki signal this month)_"]))
    if traction:
        lines.extend(["", "## Traction", ""])
        lines.extend(f"- {b}" for b in traction)
    if business:
        lines.extend(["", "## Business", ""])
        lines.extend(f"- {b}" for b in business)
    if ahead:
        lines.extend(["", "## Looking ahead", ""])
        lines.extend(f"- {b}" for b in ahead)
    lines.extend(
        [
            "",
            "---",
            "",
            "_Status: draft — never sent by company-brain._",
            "",
        ]
    )
    return "\n".join(lines)


def _try_llm_draft(month_key: str, chunks: dict[str, str]) -> str:
    try:
        from agents import Agent, Runner

        from company_brain.llm import openai_agents as oa
    except Exception:
        return ""

    excerpt = []
    for key, text in chunks.items():
        if key == "prior":
            continue
        excerpt.append(f"### {key}\n{text[:2500]}")
    prompt = (
        f"Write a concise investor update for {month_key} (300-500 words). "
        "Formal, factual, no hype, no em dashes. Sections: opening pulse, Product, "
        "Engineering, optional Traction/Business, Looking ahead. Do not invent metrics. "
        "Do not include email addresses or CRM contact lists.\n\n" + "\n\n".join(excerpt)
    )
    try:
        agent = Agent(
            name="investor_newsletter_draft",
            instructions=(
                "You draft short monthly investor updates from wiki evidence. "
                "Never claim to send email. Output markdown body only (no # title)."
            ),
            model=oa.make_model(),
        )
        result = Runner.run_sync(agent, prompt, run_config=oa.make_run_config())
        text = str(getattr(result, "final_output", "") or "").strip()
        return text
    except Exception:
        return ""
