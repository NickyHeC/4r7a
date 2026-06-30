"""Load and save ``config/external_sources.yaml``."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from company_brain.config import CONFIG_DIR, _load_yaml


class MountRecord(BaseModel):
    import_id: str
    mounted_at: str = ""
    mounted_by: str = "admin"
    file_count: int = 0
    quarantine_path: str = ""
    promote_prefix: str = ""
    status: str = "active"  # active | superseded | rejected


class ExternalSourceSpec(BaseModel):
    label: str = ""
    contact: str = ""
    description: str = ""
    default_sync: str = "company"
    mounts: list[MountRecord] = Field(default_factory=list)


class ExternalSourcesConfig(BaseModel):
    sources: dict[str, ExternalSourceSpec] = Field(default_factory=dict)

    def get(self, source_key: str) -> ExternalSourceSpec | None:
        return self.sources.get(source_key)

    def ensure_source(
        self,
        source_key: str,
        *,
        label: str = "",
        contact: str = "",
        description: str = "",
        default_sync: str = "company",
    ) -> ExternalSourceSpec:
        key = source_slug_key(source_key)
        if key not in self.sources:
            self.sources[key] = ExternalSourceSpec(
                label=label or key,
                contact=contact,
                description=description,
                default_sync=default_sync,
            )
        return self.sources[key]

    def append_mount(self, source_key: str, record: MountRecord) -> None:
        spec = self.sources.get(source_key)
        if spec is None:
            raise KeyError(source_key)
        for idx, m in enumerate(spec.mounts):
            if m.status == "active":
                spec.mounts[idx] = m.model_copy(update={"status": "superseded"})
        spec.mounts.append(record)


def source_slug_key(source_key: str) -> str:
    from company_brain.wiki.external_paths import source_slug

    return source_slug(source_key)


def load_external_sources(config_dir: Path | None = None) -> ExternalSourcesConfig:
    path = (config_dir or CONFIG_DIR) / "external_sources.yaml"
    data = _load_yaml(path)
    return ExternalSourcesConfig(**data)


def save_external_sources(cfg: ExternalSourcesConfig, config_dir: Path | None = None) -> None:
    path = (config_dir or CONFIG_DIR) / "external_sources.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(cfg.model_dump(), default_flow_style=False, sort_keys=False).strip()
        + "\n"
    )
    tmp.replace(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
