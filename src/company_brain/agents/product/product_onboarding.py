"""Product workstream onboarding — seed pages and start workstream managers.

PostHog platform onboarding stays separate (``posthog_onboarding``).

SDK: Neither (orchestration only).
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore

SEED_PAGES: list[tuple[str, str, str]] = [
    (
        "product/use-case/customer.md",
        "Customer Use Cases",
        "# Customer Use Cases\n\n"
        "How customers use the product. Absorb and humans land use-case content here; "
        "interviews may be edited in MD/Notion.\n",
    ),
    (
        "product/use-case/adjacent.md",
        "Adjacent Use Cases",
        "# Adjacent Use Cases\n\n"
        "Potential use cases adjacent to customer ones (web-search discoveries). "
        "Growth content drafts may read this page when writing blogs.\n",
    ),
    (
        "product/progress.md",
        "Product Progress",
        "# Product Progress\n\n"
        "Rough feature status from GitHub build signals and Linear project completion.\n",
    ),
    (
        "product/docs/audit.md",
        "Docs Audit",
        "# Docs Audit\n\n"
        "Gaps between internal Product Features and public llms.txt / sitemap / docs.\n",
    ),
    (
        "product/attribution/signup-match.md",
        "Signup Match",
        "# Signup Match\n\n"
        "Activity events matched to signup spikes from the configured signup source.\n",
    ),
]


class ProductOnboardingAgent(BaseAgent):
    """One-time product workstream setup + manager handoff."""

    name = "product_onboarding"

    def run(self, *, start_managers: bool = True, **kwargs: Any) -> dict[str, Any]:
        seeded = seed_workstream_pages()
        started: list[str] = []
        if start_managers:
            started = self._start_managers()
        return {
            "status": "ok",
            "seeded_pages": seeded,
            "managers_started": started,
        }

    def _start_managers(self) -> list[str]:
        from company_brain.agents.product.attribution_manager import AttributionManager
        from company_brain.agents.product.docs_manager import DocsManager
        from company_brain.agents.product.progress_manager import ProgressManager
        from company_brain.agents.product.update_manager import UpdateManager
        from company_brain.agents.product.use_case_manager import UseCaseManager
        from company_brain.runtime import get_runtime

        runtime = get_runtime()
        managers = [
            UpdateManager,
            UseCaseManager,
            DocsManager,
            ProgressManager,
            AttributionManager,
        ]
        started: list[str] = []
        for cls in managers:
            runtime.start(cls, self.config)
            started.append(cls.name)
        return started


def seed_workstream_pages() -> list[str]:
    store = LocalWikiStore()
    created: list[str] = []
    for rel, title, body in SEED_PAGES:
        if store.exists(rel):
            continue
        write_wiki_page(rel, title, body, mode=UPDATE, section="product", sync=False)
        created.append(rel)
    return created
