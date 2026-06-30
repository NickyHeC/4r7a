"""External wiki config helpers."""

from __future__ import annotations

from dataclasses import dataclass

from company_brain.config import load_yaml_config
from company_brain.wiki.import_scan import ImportLimits


@dataclass
class ExternalWikiImportConfig:
    limits: ImportLimits
    require_admin_approval: bool = True
    admin_channel: str = ""


@dataclass
class ExternalWikiCatalogConfig:
    rebuild_on_mount: bool = True
    rebuild_on_sync: bool = False
    include_employee_wiki: bool = True
    include_raw_entries: bool = False


def import_config() -> ExternalWikiImportConfig:
    block = load_yaml_config("operations").get("external_wiki") or {}
    imp = block.get("import") or {}
    employee = load_yaml_config("operations").get("employee_wiki") or {}
    employee_imp = employee.get("import") or {}
    limits = ImportLimits(
        max_zip_bytes=int(imp.get("max_zip_bytes") or 52_428_800),
        max_file_bytes=int(imp.get("max_file_bytes") or 1_048_576),
        max_files=int(imp.get("max_files") or 500),
    )
    admin_channel = str(imp.get("admin_channel") or employee_imp.get("admin_channel") or "").strip()
    return ExternalWikiImportConfig(
        limits=limits,
        require_admin_approval=bool(imp.get("require_admin_approval", True)),
        admin_channel=admin_channel,
    )


def catalog_config() -> ExternalWikiCatalogConfig:
    block = load_yaml_config("operations").get("external_wiki") or {}
    cat = block.get("catalog") or {}
    return ExternalWikiCatalogConfig(
        rebuild_on_mount=bool(cat.get("rebuild_on_mount", True)),
        rebuild_on_sync=bool(cat.get("rebuild_on_sync", False)),
        include_employee_wiki=bool(cat.get("include_employee_wiki", True)),
        include_raw_entries=bool(cat.get("include_raw_entries", False)),
    )
