"""Load ``config/bridge.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from company_brain.config import CONFIG_DIR, _load_yaml


class RateLimitsConfig(BaseModel):
    reads_per_minute: int = 60
    report_blocker_per_day: int = 20


class RollupConfig(BaseModel):
    time: str = "08:00"
    blockers_path: str = "engineering/priorities/blockers.md"
    lead_focus_path: str = "engineering/priorities/lead-focus.md"
    department: str = "engineering"
    blockers_sync: str = "location:engineering"


class ServeConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8790


class BridgeConfig(BaseModel):
    ledger_path: str = "bridge_events.jsonl"
    index_path: str = "bridge_index.json"
    tokens_path: str = "bridge-tokens.json"
    audit_log_path: str = "bridge-audit.jsonl"
    poll_interval_minutes: int = 5
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    rollup: RollupConfig = Field(default_factory=RollupConfig)
    allow_prefixes: dict[str, Any] = Field(default_factory=dict)
    skills_manifest: dict[str, str] = Field(default_factory=dict)
    serve: ServeConfig = Field(default_factory=ServeConfig)

    def config_path(self, name: str, config_dir: Path | None = None) -> Path:
        return (config_dir or CONFIG_DIR) / name

    def ledger_file(self, config_dir: Path | None = None) -> Path:
        return self.config_path(self.ledger_path, config_dir)

    def department_prefixes(self, department: str) -> list[str]:
        depts = self.allow_prefixes.get("departments") or {}
        raw = depts.get(department) or []
        return [str(p).strip("/") for p in raw if str(p).strip()]

    def company_prefixes(self) -> list[str]:
        raw = self.allow_prefixes.get("company") or []
        return [str(p).strip("/") for p in raw if str(p).strip()]


@lru_cache(maxsize=1)
def load_bridge_config(config_dir: Path | None = None) -> BridgeConfig:
    path = (config_dir or CONFIG_DIR) / "bridge.yaml"
    data = _load_yaml(path)
    return BridgeConfig(**data)
