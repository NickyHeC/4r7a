"""Product Update — monthly customer newsletter draft (never sends).

SDK: OpenAI Agents SDK when available for formal voice; template fallback.
Reads wiki Product Features + company voice; checks prior month draft / wiki-git.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.product.shared.product_slack import product_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, read_wiki_page, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

NEWSLETTER_DIR = "product/update/newsletter"
FEATURE_WIKI = "product/feature.md"
VOICE_PATH = "growth/content/voice/company.md"
WRITE_MODE = UPDATE


class ProductUpdateAgent(BaseAgent):
    """Draft a monthly customer product newsletter as wiki MD (never send)."""

    name = "product_update"
    WRITE_MODE = WRITE_MODE

    def run(
        self, *, month: str | None = None, force: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        month_key = month or now.strftime("%Y-%m")
        rel = f"{NEWSLETTER_DIR}/{month_key}.md"
        store = LocalWikiStore()
        if store.exists(rel) and not force:
            return {"status": "exists", "wiki_path": rel, "notify": False}

        features = read_wiki_page(FEATURE_WIKI) or ""
        voice = read_wiki_page(VOICE_PATH) or ""
        prior = _prior_month_body(month_key)
        body = _draft_body(month_key, features=features, voice=voice, prior=prior)
        title = f"Product Update {month_key}"
        write_wiki_page(
            rel,
            title,
            body,
            mode=WRITE_MODE,
            section="product",
            type_="draft",
            extra_frontmatter={"status": "draft", "month": month_key, "channel": "email"},
        )
        product_notifier().emit(
            Signal(
                text=(
                    f"Customer product newsletter draft ready for {month_key} "
                    f"(`{rel}`). Review and send manually — agent never sends."
                ),
                severity=ACTIONABLE,
            )
        )
        return {"status": "ok", "wiki_path": rel, "notify": True}


def _prior_month_key(month_key: str) -> str:
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _prior_month_body(month_key: str) -> str:
    prior_key = _prior_month_key(month_key)
    rel = f"{NEWSLETTER_DIR}/{prior_key}.md"
    body = read_wiki_page(rel)
    if body:
        return body
    # Optional: wiki-git backup checkout when configured
    try:
        from company_brain.agents.admin import wiki_commit_config as wiki_git

        work = wiki_git.wiki_commit_work_dir()
        path = work / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            # strip frontmatter if present
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return text.strip()
    except Exception:
        pass
    return ""


def _feature_bullets(features_md: str, *, limit: int = 8) -> list[str]:
    bullets: list[str] = []
    for line in features_md.splitlines():
        m = re.match(r"^[-*]\s+(.+)$", line.strip())
        if m:
            bullets.append(m.group(1).strip())
        elif line.startswith("## ") and "Detected" not in line:
            bullets.append(line[3:].strip())
        if len(bullets) >= limit:
            break
    return bullets


def _draft_body(month_key: str, *, features: str, voice: str, prior: str) -> str:
    bullets = _feature_bullets(features)
    voice_note = ""
    if voice.strip():
        voice_note = (
            f"_Drafted to match company voice (`{VOICE_PATH}`). Edit for tone before send._\n"
        )
    prior_note = ""
    if prior.strip():
        prior_note = (
            f"_Checked against prior draft `{_prior_month_key(month_key)}` "
            "(avoid repeating the same leads)._\n"
        )

    drafted = _try_llm_draft(month_key, bullets=bullets, voice=voice, prior=prior)
    if drafted:
        parts = [
            f"# Product Update {month_key}",
            "",
            voice_note,
            prior_note,
            drafted.strip(),
            "",
            "---",
            "",
            "_Status: draft — never sent by company-brain._",
            "",
        ]
        return "\n".join(p for p in parts if p is not None)

    lines = [
        f"# Product Update {month_key}",
        "",
        voice_note,
        prior_note,
        "Hello,",
        "",
        "Here is a concise look at core product updates this month:",
        "",
    ]
    if bullets:
        for b in bullets:
            lines.append(f"- {b}")
    else:
        lines.append("_No new feature bullets found in Product Features — fill in before send._")
    lines.extend(
        [
            "",
            "For details, see the Product Features page in your workspace.",
            "",
            "Thanks,",
            "The product team",
            "",
            "---",
            "",
            "_Status: draft — never sent by company-brain._",
            "",
        ]
    )
    return "\n".join(lines)


def _try_llm_draft(month_key: str, *, bullets: list[str], voice: str, prior: str) -> str:
    try:
        from agents import Agent, Runner

        from company_brain.llm import openai_agents as oa
    except Exception:
        return ""

    prompt = (
        f"Draft a short monthly customer email for {month_key} about core product "
        "updates. Informative, concise, formal blog-like tone. Link conceptually to "
        "features (no inventing URLs). Never claim the email was sent.\n\n"
        f"Feature bullets:\n" + "\n".join(f"- {b}" for b in bullets or ["(none)"]) + "\n\n"
        f"Company voice notes (excerpt):\n{(voice or '')[:2000]}\n\n"
        f"Prior month draft (avoid repetition):\n{(prior or '')[:2000]}\n"
    )
    try:
        agent = Agent(
            name="product_update",
            instructions=(
                "You write formal, concise customer product update emails. "
                "Output markdown body only (no subject line)."
            ),
            model=oa.make_model(agent_name="product_update"),
        )
        result = Runner.run_sync(
            agent,
            prompt,
            run_config=oa.make_run_config(agent_name="product_update"),
        )
        text = str(getattr(result, "final_output", "") or "").strip()
        return text
    except Exception:
        return ""
