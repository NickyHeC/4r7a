"""Process Scout — monthly observe → admin review proposals only.

Never auto-merges, never widens access. Absorbs optimization scout + process
artifacts + company process mining into one monthly review page.

SDK: Neither (deterministic scan + wiki review page).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.admin.llm_ops_config import load_operations_raw, previous_month
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import PROJECT_ROOT, AppConfig
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

REVIEW_TMPL = "admin/process-scout/{month}.md"
STATE_PREFIX = "admin_manager:process_scout:"


def process_scout_config() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("process_scout") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "day": int(raw.get("day") or 7),
        "time": str(raw.get("time") or "09:30"),
    }


class ProcessScoutAgent(BaseAgent):
    """Write monthly process observations as an admin review page."""

    name = "process_scout"
    WRITE_MODE = UPDATE

    def __init__(self, config: AppConfig, store: StateStore | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._store = store or StateStore()

    def run(self, *, month: str | None = None, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        month = month or previous_month()
        observations = self._observe()
        path = REVIEW_TMPL.format(month=month)
        body = self._render(month, observations)
        write_wiki_page(
            path,
            f"Process Scout — {month}",
            body,
            mode=UPDATE,
            section="admin",
            type_="review",
            sync=sync,
            sync_label="admin_only",
            extra_frontmatter={
                "month": month,
                "report": "process_scout",
                "auto_merge": False,
            },
        )
        wiki_admin_notifier().emit(
            Signal(
                text=(
                    f"*Process scout* — `{month}`\n"
                    f"{len(observations)} observation(s). Review `{path}` "
                    "(proposals only — never auto-merge)."
                ),
                severity=ACTIONABLE,
            )
        )
        return {
            "status": "ok",
            "month": month,
            "path": path,
            "observations": len(observations),
            "auto_merged": 0,
            "review_only": True,
        }

    def _observe(self) -> list[dict[str, str]]:
        obs: list[dict[str, str]] = []
        # Agent tree density
        agents_root = PROJECT_ROOT / "src" / "company_brain" / "agents"
        py_count = len(list(agents_root.rglob("*.py"))) if agents_root.is_dir() else 0
        obs.append(
            {
                "kind": "fleet",
                "title": "Agent module count",
                "detail": (
                    f"{py_count} `.py` files under `agents/`. "
                    "Consider consolidating thin specialists."
                ),
            }
        )
        # Duration / verify drift from state
        try:
            from company_brain.llm.duration import list_duration_agents

            slow = []
            for name in list_duration_agents(store=self._store)[:20]:
                slow.append(name)
            if slow:
                samples = ", ".join(f"`{n}`" for n in slow[:8])
                obs.append(
                    {
                        "kind": "runtime",
                        "title": "Timed specialists",
                        "detail": f"Recent duration samples: {samples}",
                    }
                )
        except Exception:
            self.logger.debug("Could not read duration telemetry", exc_info=True)
        # Open admin queues
        from company_brain.wiki.store import LocalWikiStore

        store = LocalWikiStore()
        queues = {
            "admin/weave-queue.md": "Weave admin queue",
            "admin/maintain/": "Maintain pages",
            "hr/offboard-proposal/": "Offboard proposals",
        }
        for prefix, label in queues.items():
            if prefix.endswith("/"):
                n = sum(1 for r in store.list() if r.startswith(prefix) and r.endswith(".md"))
                if n:
                    obs.append(
                        {
                            "kind": "queue",
                            "title": label,
                            "detail": (
                                f"{n} open page(s) under `{prefix}` — triage in console Review."
                            ),
                        }
                    )
            elif store.exists(prefix):
                obs.append(
                    {
                        "kind": "queue",
                        "title": label,
                        "detail": (
                            f"`{prefix}` has content — consider clearing after coding session."
                        ),
                    }
                )
        if len(obs) == 1:
            obs.append(
                {
                    "kind": "note",
                    "title": "No hot queues",
                    "detail": "No dense open queues detected this month. Keep observing.",
                }
            )
        return obs

    def _render(self, month: str, observations: list[dict[str, str]]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines = [
            f"# Process Scout — {month}",
            "",
            f"_Generated {now}_",
            "",
            "Proposals only. **Never auto-merge. Never widen access.** "
            "Admin / coding agent applies accepted changes.",
            "",
            "## Observations",
            "",
        ]
        for i, o in enumerate(observations, 1):
            lines.append(f"### {i}. {o['title']} (`{o['kind']}`)")
            lines.append("")
            lines.append(o["detail"])
            lines.append("")
            lines.append("- [ ] Accept / defer / reject")
            lines.append("")
        lines.extend(
            [
                "## Out of scope",
                "",
                "- Auto-writing new agents",
                "- Widening `query_grants` / bridge / Notion ACL",
                "- Cloud builder maintenance loop (tabled)",
                "",
            ]
        )
        return "\n".join(lines)
