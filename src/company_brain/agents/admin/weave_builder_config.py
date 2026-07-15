"""Weave builder settings from ``config/operations.yaml`` + env overrides."""

from __future__ import annotations

import os
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR

BUILDER_CODEX = "codex"
BUILDER_IN_HOUSE = "in_house"
BUILDER_OFF = "off"
VALID_BUILDERS = frozenset({BUILDER_CODEX, BUILDER_IN_HOUSE, BUILDER_OFF})

DEFAULTS: dict[str, Any] = {
    "builder": BUILDER_CODEX,
    "codex_image": "registry.smolmachines.com/library/codex:latest",
    "allow_prefixes": ["config/"],
    "allow_suffixes": [".yaml", ".yml", ".json"],
    "extra_allow_prefixes": ["docs/weave-requests/"],
    "prove_fail_closed": True,
    "builder_allow_hosts": [
        "api.github.com",
        "github.com",
        "api.openai.com",
    ],
    "queue_path": "admin/weave-queue.md",
}


def _load_operations() -> dict[str, Any]:
    path = CONFIG_DIR / "operations.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def weave_slack_block() -> dict[str, Any]:
    raw = _load_operations().get("slack_platform") or {}
    block = raw.get("weave") if isinstance(raw, dict) else None
    return dict(block) if isinstance(block, dict) else {}


def weave_builder_config() -> dict[str, Any]:
    """Merged Weave builder config (defaults < yaml < env)."""
    cfg = dict(DEFAULTS)
    nested = weave_slack_block()
    for key in DEFAULTS:
        if key in nested and nested[key] is not None:
            cfg[key] = nested[key]
    env_builder = (os.getenv("WEAVE_BUILDER") or "").strip().lower()
    if env_builder in VALID_BUILDERS:
        cfg["builder"] = env_builder
    env_image = (os.getenv("WEAVE_CODEX_IMAGE") or "").strip()
    if env_image:
        cfg["codex_image"] = env_image
    builder = str(cfg.get("builder") or BUILDER_CODEX).strip().lower()
    if builder not in VALID_BUILDERS:
        builder = BUILDER_CODEX
    cfg["builder"] = builder
    cfg["allow_prefixes"] = [str(p) for p in (cfg.get("allow_prefixes") or [])]
    cfg["allow_suffixes"] = [str(s) for s in (cfg.get("allow_suffixes") or [])]
    cfg["extra_allow_prefixes"] = [str(p) for p in (cfg.get("extra_allow_prefixes") or [])]
    cfg["builder_allow_hosts"] = [str(h) for h in (cfg.get("builder_allow_hosts") or [])]
    cfg["prove_fail_closed"] = bool(cfg.get("prove_fail_closed", True))
    return cfg


def resolve_builder(override: str | None = None) -> str:
    if override:
        value = override.strip().lower()
        if value in VALID_BUILDERS:
            return value
    return str(weave_builder_config()["builder"])
