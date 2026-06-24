"""Loader for engineering-department configuration (``config/engineering.yaml``).

Non-secret engineering settings (Linear team defaults, future platform config).
Secrets (API keys, OAuth tokens) come from the environment only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from company_brain.config import load_yaml_config, save_yaml_config


def load_engineering_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/engineering.yaml`` (empty dict if absent)."""
    return load_yaml_config("engineering", config_dir)


def save_engineering_config(data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Persist the engineering config back to disk."""
    save_yaml_config("engineering", data, config_dir)
