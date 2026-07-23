"""Loader for finance-specific configuration (``config/finance.yaml``).

Kept separate from the wiki/notion app config so finance settings (schedules,
Slack channel, wiki paths, learned categories) live in one place.
Contains no secrets — tokens come from the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from company_brain.config import load_yaml_config, save_yaml_config


def load_finance_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/finance.yaml`` (empty dict if absent)."""
    return load_yaml_config("finance", config_dir)


def save_finance_config(data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Persist the finance config back to disk (used to store learned categories)."""
    save_yaml_config("finance", data, config_dir)


def record_learned_categories(mapping: dict[str, str], config_dir: Path | None = None) -> None:
    """Merge counterparty->subcategory mappings learned from manual accounting.

    Stored under ``learned_categories`` so the categorization step can consult
    them on future runs (this is how agents "learn" from Manual Accounting).
    """
    cfg = load_finance_config(config_dir)
    learned = cfg.setdefault("learned_categories", {})
    learned.update({k: v for k, v in mapping.items() if k and v})
    save_finance_config(cfg, config_dir)


def vendor_dir() -> str:
    """Wiki directory for per-vendor ops comms pages (``finance/vendor/``)."""
    wiki = load_finance_config().get("wiki") or {}
    return str(wiki.get("vendor_dir", "finance/vendor"))
