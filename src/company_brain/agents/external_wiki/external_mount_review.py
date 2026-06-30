"""External Mount Review — admin wiki page + Slack notify.

SDK: Neither (wiki write + Notifier).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.external_wiki.external_wiki_slack import external_wiki_admin_notifier
from company_brain.config import AppConfig
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.duplicate_detect import parse_duplicate_report
from company_brain.wiki.external_paths import external_mount_review_path, external_quarantine_rel
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore


class ExternalMountReviewAgent(BaseAgent):
    """Write admin external mount review page and ping admin Slack."""

    name = "external_wiki_mount_review"
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        source_key: str,
        import_id: str,
        scan_blocked: bool = False,
        ping_slack: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (source_key or "").strip()
        iid = (import_id or "").strip()
        if not key or not iid:
            return {"status": "error", "reason": "source_key and import_id required"}

        store = LocalWikiStore()
        quarantine = external_quarantine_rel(key, iid)
        report_path = f"{quarantine}duplicate_report.json"
        dup = parse_duplicate_report(store.read_text(report_path)) if store.exists(report_path) else None

        scan_summary = ""
        scan_path = f"{quarantine}scan_report.json"
        if store.exists(scan_path):
            data = json.loads(store.read_text(scan_path))
            blocked = [f for f in data.get("findings") or [] if f.get("severity") == "block"]
            scan_summary = f"{len(blocked)} blocking finding(s)" if blocked else "warnings only"

        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# External mount review — {key} / {iid}",
            "",
            f"- **Source:** `{key}`",
            f"- **Import id:** `{iid}`",
            f"- **Quarantine:** `{quarantine}`",
            f"- **Submitted:** {when}",
            f"- **Scan:** {'BLOCKED' if scan_blocked else 'passed'}{(' — ' + scan_summary) if scan_summary else ''}",
            "",
            "## Duplicate report",
            "",
        ]
        if dup:
            for f in dup.files:
                lines.append(f"### `{f.path}`")
                lines.append("")
                lines.append(f"- **Verdict:** {f.verdict} (tier {f.match_tier})")
                if f.canonical:
                    lines.append(f"- **Canonical:** `{f.canonical}`")
                if f.artifact_ref:
                    lines.append(f"- **Artifact:** `{f.artifact_ref}`")
                if f.candidates:
                    lines.append(f"- **Candidates:** {', '.join(f'`{c}`' for c in f.candidates)}")
                lines.append("")
        else:
            lines.append("_No duplicate report found._")
            lines.append("")

        lines += [
            "## Admin actions",
            "",
            "Approve via `ExternalWikiImportAgent.approve(source_key=..., import_id=...)` "
            "with optional per-file decisions (`link` | `import` | `drop`).",
            "",
        ]

        rel_path = external_mount_review_path(iid)
        write_wiki_page(
            rel_path,
            f"External mount — {key}",
            "\n".join(lines).rstrip() + "\n",
            mode=UPDATE,
            section="admin",
            sync_label="admin_only",
        )

        pinged = False
        if ping_slack:
            pinged = self._ping_admin(key, iid, rel_path, scan_blocked, dup)

        return {
            "status": "ok",
            "review_page": rel_path,
            "pinged": pinged,
            "scan_blocked": scan_blocked,
        }

    def _ping_admin(self, source: str, import_id: str, rel_path: str, blocked: bool, dup) -> bool:
        link_count = sum(1 for f in (dup.files if dup else []) if f.verdict == "link")
        review_count = sum(1 for f in (dup.files if dup else []) if f.verdict == "review")
        status = "BLOCKED — needs review" if blocked else "ready for review"
        text = (
            f"External wiki mount `{import_id}` from `{source}` — {status}. "
            f"{link_count} auto-link, {review_count} need review. See wiki `{rel_path}`."
        )
        try:
            return external_wiki_admin_notifier().emit(Signal(text=text, severity=ACTIONABLE))
        except Exception:
            self.logger.exception("External mount review Slack ping failed")
            return False
