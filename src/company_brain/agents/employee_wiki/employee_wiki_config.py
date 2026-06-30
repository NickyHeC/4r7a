"""Employee wiki config helpers."""

from __future__ import annotations

from dataclasses import dataclass

from company_brain.config import load_yaml_config
from company_brain.wiki.import_scan import ImportLimits


@dataclass
class EmployeeWikiImportConfig:
    limits: ImportLimits
    require_admin_first_import: bool = True
    auto_approve_subsequent: bool = False
    admin_channel: str = ""


def import_config() -> EmployeeWikiImportConfig:
    block = load_yaml_config("operations").get("employee_wiki") or {}
    imp = block.get("import") or {}
    limits = ImportLimits(
        max_zip_bytes=int(imp.get("max_zip_bytes") or 52_428_800),
        max_file_bytes=int(imp.get("max_file_bytes") or 1_048_576),
        max_files=int(imp.get("max_files") or 500),
    )
    return EmployeeWikiImportConfig(
        limits=limits,
        require_admin_first_import=bool(imp.get("require_admin_first_import", True)),
        auto_approve_subsequent=bool(imp.get("auto_approve_subsequent", False)),
        admin_channel=str(imp.get("admin_channel") or "").strip(),
    )
