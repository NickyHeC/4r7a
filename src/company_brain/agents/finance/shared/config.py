"""Loader for finance-specific configuration (``config/finance.yaml``).

Kept separate from the wiki/notion app config so finance settings (schedules,
Slack channel, Notion page titles, learned categories) live in one place.
Contains no secrets — tokens come from the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR


def load_finance_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/finance.yaml`` (empty dict if absent)."""
    path = (config_dir or CONFIG_DIR) / "finance.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_finance_config(data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Persist the finance config back to disk (used to store learned categories)."""
    path = (config_dir or CONFIG_DIR) / "finance.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def record_learned_categories(mapping: dict[str, str], config_dir: Path | None = None) -> None:
    """Merge counterparty->subcategory mappings learned from manual accounting.

    Stored under ``learned_categories`` so the categorization step can consult
    them on future runs (this is how agents "learn" from Manual Accounting).
    """
    cfg = load_finance_config(config_dir)
    learned = cfg.setdefault("learned_categories", {})
    learned.update({k: v for k, v in mapping.items() if k and v})
    save_finance_config(cfg, config_dir)
