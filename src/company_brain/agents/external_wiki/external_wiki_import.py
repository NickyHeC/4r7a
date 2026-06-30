"""External Wiki Import — zip extract, security scan, duplicate detection.

Admin-only one-shot mount into ``wiki/external/{source}/``.

SDK: Neither (deterministic file pipeline).
"""

from __future__ import annotations

import uuid
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.external_wiki.external_mount_review import ExternalMountReviewAgent
from company_brain.agents.external_wiki.external_wiki_config import import_config
from company_brain.config import AppConfig
from company_brain.external_sources_config import load_external_sources, save_external_sources
from company_brain.runtime import get_runtime
from company_brain.wiki.duplicate_detect import detect_external_duplicates
from company_brain.wiki.external_paths import external_quarantine_rel, source_slug
from company_brain.wiki.external_promote import promote_external_mount
from company_brain.wiki.import_scan import scan_import_files
from company_brain.wiki.import_zip import extract_md_files, scan_report_json
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


class ExternalWikiImportAgent(BaseAgent):
    """Import a zip of Markdown files into external quarantine."""

    name = "external_wiki_import"

    def run(
        self,
        *,
        source_key: str,
        zip_path: str = "",
        zip_bytes: bytes | None = None,
        import_id: str | None = None,
        auto_review: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = source_slug(source_key)
        if not key:
            return {"status": "error", "reason": "source_key required"}

        raw_bytes = zip_bytes
        if raw_bytes is None:
            if not zip_path:
                return {"status": "error", "reason": "zip_path or zip_bytes required"}
            with open(zip_path, "rb") as fh:
                raw_bytes = fh.read()

        cfg = import_config()
        import_id = (import_id or uuid.uuid4().hex[:12]).strip()
        company_store = LocalWikiStore()
        sources_cfg = load_external_sources()
        sources_cfg.ensure_source(key)
        save_external_sources(sources_cfg)

        try:
            files = extract_md_files(raw_bytes, cfg.limits)
        except ValueError as exc:
            return {"status": "error", "reason": str(exc), "import_id": import_id}

        scan = scan_import_files(files, limits=cfg.limits, zip_bytes=len(raw_bytes))
        quarantine = external_quarantine_rel(key, import_id)
        for rel, content in files.items():
            dest = f"{quarantine}{rel}".replace("//", "/")
            company_store.write(dest, MarkdownDoc(body=content))

        dup_report = detect_external_duplicates(
            files,
            source_key=key,
            import_id=import_id,
            company_store=company_store,
        )
        company_store.write_text(f"{quarantine}duplicate_report.json", dup_report.serialize())
        if scan.findings:
            company_store.write_text(f"{quarantine}scan_report.json", scan_report_json(scan))

        review = None
        if auto_review:
            review = get_runtime().run(
                ExternalMountReviewAgent,
                self.config,
                source_key=key,
                import_id=import_id,
                scan_blocked=not scan.ok,
            )

        status = "blocked" if not scan.ok else "pending_review"
        return {
            "status": status,
            "import_id": import_id,
            "source": key,
            "quarantine": quarantine,
            "scan": {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
            "duplicate_report": dup_report.to_dict(),
            "review": review,
        }

    def approve(
        self,
        *,
        source_key: str,
        import_id: str,
        decisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Admin approval path — promote quarantine into ``wiki/external/{source}/``."""
        key = source_slug(source_key)
        result = promote_external_mount(key, import_id, decisions=decisions)
        return {"status": "ok", **result.to_dict()}
