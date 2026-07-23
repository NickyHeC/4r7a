"""Self-heal v1 — on verify failure / alert, propose a Weave-queue item (or draft PR).

Never auto-merges. Optional sandbox note when available. Cloud builder loop stays tabled.

SDK: Neither (deterministic proposal + optional gh draft PR when ``head`` is set).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.admin.llm_ops_config import load_operations_raw
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore, is_handled, mark_handled
from company_brain.config import AppConfig
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import APPEND, write_wiki_page

logger = logging.getLogger(__name__)

WEAVE_QUEUE = "admin/weave-queue.md"
STATE_PREFIX = "admin:self_heal:"


def self_heal_config() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("self_heal") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "draft_pr": bool(raw.get("draft_pr", True)),
        "sandbox_first": bool(raw.get("sandbox_first", True)),
        "queue_on_fail": bool(raw.get("queue_on_fail", True)),
    }


class SelfHealAgent(BaseAgent):
    """Propose a fix path after a specialist verify failure — never merge."""

    name = "self_heal"
    WRITE_MODE = APPEND
    max_iterations = 1
    fleet_exempt = True

    def __init__(self, config: AppConfig, store: StateStore | None = None, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._store = store or StateStore()
        self._cfg = self_heal_config()

    def should_run(self, **kwargs: Any) -> bool:
        return bool(self._cfg.get("enabled", True))

    def run(
        self,
        *,
        agent_name: str,
        reason: str,
        detail: str = "",
        head: str | None = None,
        sync: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self._cfg.get("enabled", True):
            return {"status": "skipped", "reason": "self_heal_disabled", "auto_merged": False}

        sig = hashlib.sha256(f"{agent_name}:{reason}:{detail[:200]}".encode()).hexdigest()[:16]
        key = STATE_PREFIX + sig
        if is_handled(key, sig, store=self._store):
            return {
                "status": "skipped",
                "reason": "already_handled",
                "key": key,
                "auto_merged": False,
            }

        sandbox_note = "not_run"
        if self._cfg.get("sandbox_first"):
            sandbox_note = "available_if_runtime_supports"
            try:
                from company_brain.runtime import get_runtime

                rt = get_runtime()
                if not hasattr(rt, "verify_in_sandbox"):
                    sandbox_note = "no_sandbox_api"
            except Exception:
                sandbox_note = "runtime_unavailable"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        section = (
            f"## Self-heal proposal — `{agent_name}` ({now})\n\n"
            f"**Reason:** {reason}\n\n"
            f"{detail.strip() or '_No detail_'}\n\n"
            f"- Sandbox first: `{self._cfg.get('sandbox_first')}` ({sandbox_note})\n"
            f"- Auto-merge: **never**\n"
            f"- Action: review draft PR if opened, else triage this queue entry\n"
        )

        pr_url = ""
        if self._cfg.get("draft_pr") and head:
            pr_url = self._try_draft_pr(agent_name, reason, detail, head=head) or ""

        queued = False
        if self._cfg.get("queue_on_fail") or not pr_url:
            write_wiki_page(
                WEAVE_QUEUE,
                "Weave Admin Queue",
                section,
                mode=APPEND,
                section="admin",
                type_="queue",
                sync=sync,
                sync_label="admin_only",
            )
            queued = True

        mark_handled(key, sig, store=self._store)
        wiki_admin_notifier().emit(
            Signal(
                text=(
                    f"*Self-heal proposal* — `{agent_name}`\n"
                    f"{reason}"
                    + (f"\nDraft PR: {pr_url}" if pr_url else "\nQueued on `admin/weave-queue.md`")
                ),
                severity=ACTIONABLE,
            )
        )
        return {
            "status": "ok",
            "agent_name": agent_name,
            "pr_url": pr_url or None,
            "queued": queued,
            "auto_merged": False,
            "key": key,
        }

    def _try_draft_pr(
        self,
        agent_name: str,
        reason: str,
        detail: str,
        *,
        head: str,
    ) -> str | None:
        """Open a draft PR only when a real head branch is supplied — never invents code."""
        try:
            from company_brain.agents.engineering.github.gh import create_pull_request, gh_available
        except Exception:
            self.logger.debug("GitHub PR helper unavailable", exc_info=True)
            return None
        if not gh_available() or not head.strip():
            return None
        try:
            pr = create_pull_request(
                title=f"[self-heal] {agent_name}: {reason[:60]}",
                body=(
                    f"## Self-heal proposal (auto)\n\n"
                    f"Agent: `{agent_name}`\n\n"
                    f"Reason: {reason}\n\n"
                    f"{detail}\n\n"
                    f"**Never auto-merge.** Human / coding agent must apply the fix.\n"
                ),
                head=head.strip(),
                draft=True,
            )
            return str(pr.get("url") or "") or None
        except Exception:
            self.logger.debug("self_heal draft PR failed", exc_info=True)
            return None


def propose_self_heal(
    config: AppConfig,
    *,
    agent_name: str,
    reason: str,
    detail: str = "",
    head: str | None = None,
) -> dict[str, Any] | None:
    """Best-effort entry point from BaseAgent.execute — never raises to caller."""
    cfg = self_heal_config()
    if not cfg.get("enabled", True):
        return None
    if agent_name in {"self_heal", "admin_manager"}:
        return None
    try:
        from company_brain.runtime import get_runtime

        return get_runtime().run(
            SelfHealAgent,
            config,
            agent_name=agent_name,
            reason=reason,
            detail=detail,
            head=head,
            sync=True,
        )
    except Exception:
        logger.debug("Self-heal proposal failed", exc_info=True)
        return None
