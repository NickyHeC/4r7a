"""Shared zip-of-markdown extraction for import pipelines."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePosixPath

from company_brain.wiki.import_scan import ImportLimits


def extract_md_files(raw_bytes: bytes, limits: ImportLimits | None = None) -> dict[str, str]:
    limits = limits or ImportLimits()
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
                rel = safe_rel_path(str(name))
                files[rel] = zf.read(info).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid zip file") from exc
    if not files:
        raise ValueError("zip contains no .md files")
    return files


def safe_rel_path(name: str) -> str:
    parts = [p for p in PurePosixPath(name).parts if p not in (".", "..", "")]
    if not parts:
        raise ValueError("empty path in zip")
    return "/".join(parts)


def scan_report_json(scan) -> str:
    return json.dumps(
        {"ok": scan.ok, "findings": [f.__dict__ for f in scan.findings]},
        indent=2,
    )
