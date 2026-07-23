"""On-demand platform sync kicked by ``@wiki sync now <platform>``."""

from __future__ import annotations

from typing import Any, Callable

SYNC_ALIASES: dict[str, str] = {
    "notion": "notion",
    "crm": "crm",
    "wiki": "notion",
    "github": "github",
    "posthog": "posthog",
}


def sync_platform(platform: str, *, force: bool = True) -> dict[str, Any]:
    """Run a best-effort sync for ``platform``. Never widens ACL."""
    key = (platform or "").strip().lower()
    alias = SYNC_ALIASES.get(key, key)
    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "notion": _sync_notion,
        "crm": _sync_crm,
        "github": lambda: _sync_github(force=force),
        "posthog": lambda: _sync_posthog(force=force),
    }
    fn = handlers.get(alias)
    if not fn:
        return {
            "status": "error",
            "reason": f"unknown platform '{platform}'",
            "supported": sorted(set(SYNC_ALIASES)),
        }
    try:
        result = fn()
        return {"status": "ok", "platform": alias, "result": result}
    except Exception as exc:
        return {"status": "error", "platform": alias, "reason": str(exc)[:300]}


def _sync_notion() -> dict[str, Any]:
    from company_brain.config import load_config
    from company_brain.notion.sync import NotionSync
    from company_brain.wiki.store import LocalWikiStore

    synced = NotionSync(store=LocalWikiStore(), config=load_config()).sync_all()
    return {"synced": len(synced)}


def _sync_crm() -> dict[str, Any]:
    from company_brain.crm.notion_sync import sync_all_crm

    out = sync_all_crm()
    return out if isinstance(out, dict) else {"result": out}


def _sync_github(*, force: bool = True) -> dict[str, Any]:
    import asyncio

    from company_brain.agents.engineering.github_manager import GitHubManager
    from company_brain.config import load_config

    del force
    agent = GitHubManager(load_config())
    asyncio.run(agent._morning_check())
    return {"status": "ok", "ran": "morning_check"}


def _sync_posthog(*, force: bool = True) -> dict[str, Any]:
    from company_brain.agents.product.posthog_manager import PosthogManager
    from company_brain.config import load_config
    from company_brain.runtime import get_runtime

    return get_runtime().run(PosthogManager, load_config(), once=True, force=force) or {
        "status": "ok"
    }
