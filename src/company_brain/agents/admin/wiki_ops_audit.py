"""Wiki ops audit — monthly cross-building maintenance suggestions (review only).

Catalog summary, broken wikilinks, orphan MD candidates, migrate-names suggestions,
and stale ``admin_only`` pages. Never auto-renames, never auto-merges.

SDK: Neither (deterministic scan + wiki review page).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.admin.llm_ops_config import load_operations_raw, previous_month
from company_brain.agents.base import BaseAgent
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.name_migrate import WIKILINK_RE, plan_migration
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import CONTROL_FILES, LocalWikiStore

REVIEW_TMPL = "admin/wiki-ops/{month}.md"
STATE_PREFIX = "admin_manager:wiki_ops_audit:"

_SKIP_PREFIXES = (
    "raw/",
    "admin/import-review/",
    "admin/mount-review/",
    "admin/notion-orphan-review/",
    "admin/process-scout/",
    "admin/wiki-ops/",
    "admin/doc-hygiene/",
    "admin/maintain/",
    "hr/offboard-proposal/",
)


def wiki_ops_audit_config() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("wiki_ops_audit") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "day": int(raw.get("day") or 8),
        "time": str(raw.get("time") or "09:45"),
        "max_items": int(raw.get("max_items") or 40),
    }


class WikiOpsAuditAgent(BaseAgent):
    """Write monthly wiki maintenance suggestions as an admin review page."""

    name = "wiki_ops_audit"
    WRITE_MODE = UPDATE

    def run(self, *, month: str | None = None, sync: bool = True, **kwargs: Any) -> dict[str, Any]:
        month = month or previous_month()
        cfg = wiki_ops_audit_config()
        store = LocalWikiStore()
        findings = self._scan(store, max_items=int(cfg["max_items"]))
        path = REVIEW_TMPL.format(month=month)
        body = self._render(month, findings)
        write_wiki_page(
            path,
            f"Wiki Ops Audit — {month}",
            body,
            mode=UPDATE,
            section="admin",
            type_="review",
            sync=sync,
            sync_label="admin_only",
            extra_frontmatter={
                "month": month,
                "report": "wiki_ops_audit",
                "auto_merge": False,
            },
        )
        total = sum(len(v) for v in findings.values() if isinstance(v, list))
        if total:
            wiki_admin_notifier().emit(
                Signal(
                    text=(
                        f"*Wiki ops audit* — `{month}`\n"
                        f"{total} suggestion(s). Review `{path}` (never auto-apply)."
                    ),
                    severity=ACTIONABLE,
                )
            )
        return {
            "status": "ok",
            "month": month,
            "path": path,
            "counts": {k: len(v) if isinstance(v, list) else v for k, v in findings.items()},
            "auto_applied": 0,
        }

    def _scan(self, store: LocalWikiStore, *, max_items: int) -> dict[str, Any]:
        paths = [p for p in store.list() if p.endswith(".md") and p not in CONTROL_FILES]
        existing = set(paths)
        broken: list[str] = []
        orphans: list[str] = []
        stale_admin: list[str] = []
        linked_targets: set[str] = set()

        for rel in paths:
            try:
                doc = store.read(rel)
            except (OSError, FileNotFoundError):
                continue
            body = doc.body or ""
            for target, _label in WIKILINK_RE.findall(body):
                t = target.strip().lstrip("./")
                if not t or t.startswith("http"):
                    continue
                # Resolve relative-ish targets to .md paths when possible
                candidates = [t if t.endswith(".md") else f"{t}.md", t]
                linked_targets.update(candidates)
                if not any(c in existing for c in candidates):
                    # Also try basename match under same section
                    if "/" not in t and any(
                        p.endswith(f"/{t}.md") or p.endswith(f"/{t}") for p in existing
                    ):
                        continue
                    broken.append(f"`{rel}` → `[[{target}]]`")
                    if len(broken) >= max_items:
                        break
            sync = str(doc.frontmatter.get("sync") or "")
            if sync == "admin_only" and not rel.startswith("admin/"):
                # Non-admin path marked admin_only — audit for staleness / mis-label
                stale_admin.append(rel)
            elif sync == "admin_only" and rel.startswith("admin/"):
                # Long-lived review stubs with almost no body
                lines = [ln for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
                if len(lines) <= 1 and "review" in rel:
                    stale_admin.append(rel)

        for rel in paths:
            if any(rel.startswith(p) for p in _SKIP_PREFIXES):
                continue
            stem = rel[:-3] if rel.endswith(".md") else rel
            base = stem.split("/")[-1]
            if (
                rel not in linked_targets
                and f"{stem}.md" not in linked_targets
                and base not in {t.split("/")[-1].removesuffix(".md") for t in linked_targets}
            ):
                # Only flag thin leaves that look abandoned (no inbound + short body)
                try:
                    doc = store.read(rel)
                    if len((doc.body or "").strip()) < 80:
                        orphans.append(rel)
                except (OSError, FileNotFoundError):
                    continue
            if len(orphans) >= max_items:
                break

        migrate_suggestions: list[str] = []
        try:
            plan = plan_migration(company_store=store, include_routing=True, rewrite_links=False)
            for rename in plan.renames[:max_items]:
                migrate_suggestions.append(f"`{rename.old_path}` → `{rename.new_path}`")
        except Exception:
            self.logger.debug("Could not build naming migration suggestions", exc_info=True)

        catalog_note = "Run `company-brain catalog` to regenerate `admin/content-catalog.md`."
        try:
            from company_brain.wiki.content_catalog import build_content_catalog

            cat = build_content_catalog(store=store, include_employee_wiki=False)
            n_pages = cat.company_page_count + cat.external_page_count + len(cat.admin_pages)
            catalog_note = f"Catalog builder ok ({n_pages} pages). {catalog_note}"
        except Exception:
            catalog_note = f"Catalog builder unavailable. {catalog_note}"

        return {
            "broken_links": broken[:max_items],
            "orphan_md": orphans[:max_items],
            "migrate_names": migrate_suggestions[:max_items],
            "stale_admin_only": stale_admin[:max_items],
            "catalog": catalog_note,
        }

    def _render(self, month: str, findings: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines = [
            f"# Wiki Ops Audit — {month}",
            "",
            f"_Generated {now}_",
            "",
            "Suggestions only. **Never auto-rename / auto-merge / widen access.**",
            "",
            "## Content catalog",
            "",
            str(findings.get("catalog") or "—"),
            "",
            "## Broken wikilinks",
            "",
        ]
        broken = findings.get("broken_links") or []
        if not broken:
            lines.append("_None found (sample)._")
        else:
            for item in broken:
                lines.append(f"- {item}")
        lines.extend(["", "## Orphan MD (thin, unlinked)", ""])
        orphans = findings.get("orphan_md") or []
        if not orphans:
            lines.append("_None found (heuristic)._")
        else:
            for item in orphans:
                lines.append(f"- `{item}`")
        lines.extend(["", "## migrate-names suggestions", ""])
        mig = findings.get("migrate_names") or []
        if not mig:
            lines.append("_No pending renames in plan._")
        else:
            for item in mig:
                lines.append(f"- {item}")
            lines.append("")
            lines.append("Apply via `company-brain migrate-names --apply` after review.")
        lines.extend(["", "## Stale / odd `admin_only`", ""])
        stale = findings.get("stale_admin_only") or []
        if not stale:
            lines.append("_None flagged._")
        else:
            for item in stale:
                lines.append(f"- `{item}`")
        lines.extend(
            [
                "",
                "## Out of scope",
                "",
                "- Process / optimization scout (see `admin/process-scout/`)",
                "- Notion orphan crawl (separate weekly agent)",
                "",
            ]
        )
        return "\n".join(lines)
