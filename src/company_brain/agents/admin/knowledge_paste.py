"""Admin knowledge paste — quarantine, scan, review, promote.

Lightweight path for misc external notes (e.g. Bookface paste). Not a platform API.
SDK: Neither (deterministic file pipeline).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.llm.admin_notify import wiki_admin_notifier
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.duplicate_detect import detect_external_duplicates
from company_brain.wiki.import_scan import ImportLimits, scan_import_files
from company_brain.wiki.import_zip import scan_report_json
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc

QUARANTINE_PREFIX = "admin/_quarantine/paste"
REVIEW_DIR = "admin/knowledge-review"
DEFAULT_DEST_DIR = "admin/knowledge"
WRITE_MODE = UPDATE
SLUG_RE = re.compile(r"[^a-z0-9]+")


def _paste_config() -> dict[str, Any]:
    from company_brain.agents.admin.llm_ops_config import load_operations_raw

    raw = (load_operations_raw().get("admin") or {}).get("knowledge_paste") or {}
    return {
        "max_body_bytes": int(raw.get("max_body_bytes") or 524_288),
        "default_sync": str(raw.get("default_sync") or "admin_only"),
        "default_section": str(raw.get("default_section") or DEFAULT_DEST_DIR),
    }


def _slugify(title: str) -> str:
    base = SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return (base or "note")[:60]


class KnowledgePasteAgent(BaseAgent):
    """Paste untrusted markdown into quarantine and open an admin review page."""

    name = "knowledge_paste"
    WRITE_MODE = WRITE_MODE

    def run(
        self,
        *,
        title: str,
        body: str = "",
        file_path: str = "",
        import_id: str | None = None,
        dest: str | None = None,
        to_raw: bool = False,
        sync_label: str | None = None,
        approve: bool = False,
        force_approve: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cfg = _paste_config()
        sync_label = sync_label or cfg["default_sync"]
        title = (title or "").strip()
        if not title:
            return {"status": "error", "reason": "title required"}

        content = (body or "").strip()
        if file_path:
            content = Path(file_path).read_text(encoding="utf-8")
        if not content.strip():
            return {"status": "error", "reason": "body or file_path required"}

        import_id = (import_id or uuid.uuid4().hex[:12]).strip()
        slug = _slugify(title)
        rel_name = f"{slug}.md"
        files = {rel_name: content}
        limits = ImportLimits(max_files=10, max_file_bytes=cfg["max_body_bytes"])
        scan = scan_import_files(files, limits=limits)
        store = LocalWikiStore()
        quarantine = f"{QUARANTINE_PREFIX}/{import_id}/"
        store.write(f"{quarantine}{rel_name}", MarkdownDoc(body=content))
        if scan.findings:
            store.write_text(f"{quarantine}scan_report.json", scan_report_json(scan))

        try:
            dup = detect_external_duplicates(
                files,
                source_key="admin_paste",
                import_id=import_id,
                company_store=store,
            )
            dup_dict = dup.to_dict()
        except Exception:
            dup_dict = {"status": "skipped"}

        review_path = f"{REVIEW_DIR}/{import_id}.md"
        status = "blocked" if not scan.ok else "pending_review"
        review_body = _review_body(
            title=title,
            import_id=import_id,
            status=status,
            scan=scan,
            dup=dup_dict,
            quarantine=quarantine,
            dest=dest,
            to_raw=to_raw,
            sync_label=sync_label,
            excerpt=content[:2000],
        )
        write_wiki_page(
            review_path,
            f"Knowledge Review — {title}",
            review_body,
            mode=WRITE_MODE,
            section="admin",
            type_="page",
            extra_frontmatter={
                "sync": "admin_only",
                "import_id": import_id,
                "paste_status": status,
            },
            sync=False,
        )
        wiki_admin_notifier().emit(
            Signal(
                text=f"Knowledge paste `{import_id}` is {status} — review `{review_path}`",
                severity=ACTIONABLE,
            )
        )

        result: dict[str, Any] = {
            "status": status,
            "import_id": import_id,
            "review_path": review_path,
            "quarantine": quarantine,
            "scan": {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
            "duplicate_report": dup_dict,
        }

        if approve or force_approve:
            if not scan.ok and not force_approve:
                result["promote"] = {"status": "blocked", "reason": "scan failed"}
                return result
            promote = self.approve(
                import_id=import_id,
                title=title,
                dest=dest,
                to_raw=to_raw,
                sync_label=sync_label,
                force=force_approve,
            )
            result["promote"] = promote
            result["status"] = promote.get("status", result["status"])
        return result

    def approve(
        self,
        *,
        import_id: str,
        title: str | None = None,
        dest: str | None = None,
        to_raw: bool = False,
        sync_label: str | None = None,
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cfg = _paste_config()
        sync_label = sync_label or cfg["default_sync"]
        store = LocalWikiStore()
        quarantine = f"{QUARANTINE_PREFIX}/{import_id}"
        content = ""
        rel_src = ""
        for rel in store.list(quarantine):
            if not rel.endswith(".md"):
                continue
            try:
                doc = store.read(rel)
                content = doc.body
                rel_src = rel
                break
            except FileNotFoundError:
                continue
        if not content:
            return {"status": "error", "reason": "quarantine content missing"}

        scan_path = f"{quarantine}scan_report.json"
        if store.exists(scan_path) and not force:
            # Re-scan content
            scan = scan_import_files(
                {"note.md": content},
                limits=ImportLimits(max_files=10, max_file_bytes=cfg["max_body_bytes"]),
            )
            if not scan.ok:
                return {"status": "blocked", "reason": "scan failed", "scan": scan.ok}

        title = (title or "Knowledge note").strip()
        slug = _slugify(title)
        now = datetime.now(timezone.utc).isoformat()

        if to_raw:
            from company_brain.config import resolve_raw_dir
            from company_brain.ingestion.entry import RawEntry

            entry = RawEntry(
                source_type="admin_paste",
                source_id=import_id,
                title=title,
                content=content.strip(),
                metadata={
                    "import_id": import_id,
                    "pasted_at": now,
                    "pasted_by": "admin",
                    "absorb_lane": "urgent",
                },
                tags=["admin_paste", "urgent"],
            )
            entries_dir = resolve_raw_dir() / "entries"
            entries_dir.mkdir(parents=True, exist_ok=True)
            raw_path = entries_dir / entry.filename()
            tmp = raw_path.with_suffix(".md.tmp")
            tmp.write_text(entry.to_doc().serialize(), encoding="utf-8")
            tmp.replace(raw_path)
            raw_rel = f"raw/entries/{entry.filename()}"
            _mark_review_promoted(import_id, dest=raw_rel, status="promoted_raw")
            return {"status": "promoted", "path": str(raw_path), "mode": "raw", "raw_id": entry.id}

        dest_rel = (dest or f"{cfg['default_section']}/{slug}.md").strip().lstrip("/")
        if not dest_rel.endswith(".md"):
            dest_rel = f"{dest_rel}.md"
        body = "\n".join(
            [
                f"# {title}",
                "",
                content.strip(),
                "",
                f"_Promoted from admin paste `{import_id}` ({rel_src})._",
                "",
            ]
        )
        write_wiki_page(
            dest_rel,
            title,
            body,
            mode=UPDATE,
            section=dest_rel.split("/", 1)[0],
            type_="page",
            sources=[f"admin_paste:{import_id}"],
            extra_frontmatter={
                "sync": sync_label,
                "source": "admin_paste",
                "import_id": import_id,
                "pasted_at": now,
                "pasted_by": "admin",
            },
            sync=True,
        )
        _mark_review_promoted(import_id, dest=dest_rel, status="promoted")
        return {"status": "promoted", "path": dest_rel, "mode": "wiki"}


def _mark_review_promoted(import_id: str, *, dest: str, status: str) -> None:
    review_path = f"{REVIEW_DIR}/{import_id}.md"
    try:
        from company_brain.wiki.publish import read_wiki_page

        existing = read_wiki_page(review_path) or ""
    except Exception:
        existing = ""
    note = f"\n\n## Promotion\n\n- status: `{status}`\n- dest: `{dest}`\n"
    write_wiki_page(
        review_path,
        f"Knowledge Review — {import_id}",
        (existing or f"# Knowledge Review — {import_id}\n") + note,
        mode=UPDATE,
        section="admin",
        type_="page",
        extra_frontmatter={"sync": "admin_only", "paste_status": status, "import_id": import_id},
        sync=False,
    )


def _review_body(
    *,
    title: str,
    import_id: str,
    status: str,
    scan: Any,
    dup: dict[str, Any],
    quarantine: str,
    dest: str | None,
    to_raw: bool,
    sync_label: str,
    excerpt: str,
) -> str:
    findings = (
        "\n".join(f"- **{f.severity}** `{f.path}`: {f.reason}" for f in (scan.findings or []))
        or "- (none)"
    )
    return "\n".join(
        [
            f"# Knowledge Review — {title}",
            "",
            f"- import_id: `{import_id}`",
            f"- status: `{status}`",
            f"- quarantine: `{quarantine}`",
            f"- proposed dest: `{dest or DEFAULT_DEST_DIR + '/' + _slugify(title) + '.md'}`",
            f"- to_raw: `{to_raw}`",
            f"- sync: `{sync_label}`",
            "",
            "## Scan",
            "",
            findings,
            "",
            "## Duplicates",
            "",
            f"```json\n{dup}\n```",
            "",
            "## Excerpt",
            "",
            excerpt,
            "",
            "## Approve",
            "",
            "```bash",
            f"company-brain admin knowledge approve --import-id {import_id} --title {title!r}",
            "```",
            "",
        ]
    )


def is_untrusted_wiki_path(rel_path: str) -> bool:
    """Paths that must not be written via raw admin console save."""
    rel = rel_path.strip().lstrip("/")
    prefixes = (
        "external/",
        "admin/knowledge/",
        "admin/_quarantine/",
        "raw/",
    )
    return any(rel.startswith(p) for p in prefixes)
