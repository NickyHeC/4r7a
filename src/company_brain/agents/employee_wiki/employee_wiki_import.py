"""Employee Wiki Import — zip extract, security scan, duplicate detection.

Specialist agent: extracts a zip of ``.md`` files into quarantine, runs
deterministic security scan + duplicate detection, then dispatches admin review.

SDK: Neither (deterministic file pipeline).
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.employee_wiki.employee_wiki_config import import_config
from company_brain.agents.employee_wiki.import_review import ImportReviewAgent
from company_brain.agents.gates import StateStore
from company_brain.config import AppConfig
from company_brain.runtime import get_runtime
from company_brain.wiki.duplicate_detect import detect_duplicates
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.import_promote import member_quarantine_rel, promote_import
from company_brain.wiki.import_scan import scan_import_files
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


class EmployeeWikiImportAgent(BaseAgent):
    """Import a zip of Markdown files into member quarantine."""

    name = "employee_wiki_import"

    def __init__(self, config: AppConfig, **kwargs: Any):
        super().__init__(config, **kwargs)
        self._state = StateStore()

    def run(
        self,
        *,
        member_key: str,
        zip_path: str = "",
        zip_bytes: bytes | None = None,
        import_id: str | None = None,
        auto_review: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if not key:
            return {"status": "error", "reason": "member_key required"}

        raw_bytes = zip_bytes
        if raw_bytes is None:
            if not zip_path:
                return {"status": "error", "reason": "zip_path or zip_bytes required"}
            with open(zip_path, "rb") as fh:
                raw_bytes = fh.read()

        cfg = import_config()
        import_id = (import_id or uuid.uuid4().hex[:12]).strip()
        employee_store = LocalEmployeeWikiStore()
        company_store = LocalWikiStore()

        try:
            files = _extract_md_files(raw_bytes, cfg.limits)
        except ValueError as exc:
            return {"status": "error", "reason": str(exc), "import_id": import_id}

        scan = scan_import_files(files, limits=cfg.limits, zip_bytes=len(raw_bytes))
        quarantine = member_quarantine_rel(key, import_id)
        for rel, content in files.items():
            dest = f"{quarantine}{rel}".replace("//", "/")
            employee_store.write(dest, MarkdownDoc(body=content))

        dup_report = detect_duplicates(
            files,
            member_key=key,
            import_id=import_id,
            company_store=company_store,
            employee_store=employee_store,
        )
        employee_store.write_text(f"{quarantine}duplicate_report.json", dup_report.serialize())
        if scan.findings:
            employee_store.write_text(
                f"{quarantine}scan_report.json",
                _scan_json(scan),
            )

        if not scan.ok:
            review = None
            if auto_review:
                review = get_runtime().run(
                    ImportReviewAgent,
                    self.config,
                    member_key=key,
                    import_id=import_id,
                    scan_blocked=True,
                )
            return {
                "status": "blocked",
                "import_id": import_id,
                "quarantine": quarantine,
                "scan": {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
                "duplicate_report": dup_report.to_dict(),
                "review": review,
            }

        import_count = int(self._state.get(f"employee_import_count:{key}") or 0)
        is_first = import_count == 0
        needs_admin = is_first or cfg.require_admin_first_import

        can_auto = (
            not needs_admin
            and cfg.auto_approve_subsequent
            and all(f.verdict in ("link", "import") for f in dup_report.files)
        )

        review = None
        if auto_review and needs_admin:
            review = get_runtime().run(
                ImportReviewAgent,
                self.config,
                member_key=key,
                import_id=import_id,
                scan_blocked=False,
            )

        promoted = None
        if can_auto:
            promoted = promote_import(key, import_id, store=employee_store)
            self._state.set(f"employee_import_count:{key}", import_count + 1)

        return {
            "status": "ok" if not needs_admin or can_auto else "pending_review",
            "import_id": import_id,
            "quarantine": quarantine,
            "first_import": is_first,
            "needs_admin": needs_admin,
            "scan": {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
            "duplicate_report": dup_report.to_dict(),
            "review": review,
            "promoted": promoted.to_dict() if promoted else None,
        }

    def approve(
        self,
        *,
        member_key: str,
        import_id: str,
        decisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Admin approval path — promote quarantine files into member wiki."""
        key = (member_key or "").strip()
        result = promote_import(key, import_id, decisions=decisions)
        count = int(self._state.get(f"employee_import_count:{key}") or 0)
        self._state.set(f"employee_import_count:{key}", count + 1)
        return {"status": "ok", **result.to_dict()}


def _extract_md_files(raw_bytes: bytes, limits) -> dict[str, str]:
    if len(raw_bytes) > limits.max_zip_bytes:
        raise ValueError(f"zip exceeds {limits.max_zip_bytes} bytes")
    files: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            if len(zf.namelist()) > limits.max_files:
                raise ValueError(f"too many files in zip (>{limits.max_files})")
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = PurePosixPath(info.filename)
                if name.parts and name.parts[0].startswith("__MACOSX"):
                    continue
                if not str(name).lower().endswith(".md"):
                    raise ValueError(f"non-.md file in zip: {info.filename}")
                if info.file_size > limits.max_file_bytes:
                    raise ValueError(f"file too large: {info.filename}")
                rel = _safe_rel_path(str(name))
                files[rel] = zf.read(info).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid zip file") from exc
    if not files:
        raise ValueError("zip contains no .md files")
    return files


def _safe_rel_path(name: str) -> str:
    parts = [p for p in PurePosixPath(name).parts if p not in (".", "..", "")]
    if not parts:
        raise ValueError("empty path in zip")
    return "/".join(parts)


def _scan_json(scan) -> str:
    return json.dumps(
        {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
        indent=2,
    )
