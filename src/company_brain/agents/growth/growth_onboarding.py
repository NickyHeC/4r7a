"""Growth workstream onboarding — seed pages and start workstream managers.

Platform onboarding (Discord / Google Ads) stays separate. This agent hands off
activity / content / competitor / lead managers after light seeds.

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.crm.seeds import ensure_crm_seeds
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore


class GrowthOnboardingAgent(BaseAgent):
    """One-time growth workstream setup + manager handoff."""

    name = "growth_onboarding"

    def run(self, *, start_managers: bool = True, **kwargs: Any) -> dict[str, Any]:
        ensure_crm_seeds()
        seeded = _seed_pages()

        from company_brain.agents.growth.competitor.discover import CompetitorDiscoverAgent
        from company_brain.runtime import get_runtime

        discover = get_runtime().run(CompetitorDiscoverAgent, self.config, force=True)

        started: list[str] = []
        if start_managers:
            started = self._start_managers()

        return {
            "status": "ok",
            "seeded_pages": seeded,
            "competitor_discover": discover,
            "managers_started": started,
        }

    def _start_managers(self) -> list[str]:
        from company_brain.agents.growth.activity_manager import ActivityManager
        from company_brain.agents.growth.competitor_manager import CompetitorManager
        from company_brain.agents.growth.content_manager import ContentManager
        from company_brain.agents.growth.lead_manager import LeadManager
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        managers = [
            ActivityManager,
            ContentManager,
            CompetitorManager,
            LeadManager,
        ]
        started: list[str] = []
        for cls in managers:
            runtime.start(cls, self.config)
            started.append(cls.name)
        return started


def _seed_pages() -> list[str]:
    store = LocalWikiStore()
    created: list[str] = []
    seeds = [
        (
            "growth/activity/_index.md",
            "Company Activity",
            "# Company Activity\n\nRegistered company events.\n",
        ),
        (
            "growth/content/voice/company.md",
            "Company Voice",
            "# Company Voice\n\nLiving notes on company public voice.\n",
        ),
        (
            "growth/content/trend-watch.md",
            "Trend Watch",
            "# Trend Watch\n\nHot online discussions relevant to the company.\n",
        ),
        (
            "growth/content/posting-schedule.md",
            "Posting Schedule",
            "# Posting Schedule\n\nOpen drafts and cadence guidance.\n",
        ),
        (
            "growth/content/published.md",
            "Published Company Content",
            "# Published Company Content\n\nArchive of company-published public content.\n",
        ),
    ]
    for rel, title, body in seeds:
        if store.exists(rel):
            continue
        write_wiki_page(rel, title, body, mode=UPDATE, section="growth", sync=False)
        created.append(rel)
    return created
