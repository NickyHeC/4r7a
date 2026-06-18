"""Loader for operations-department configuration (``config/operations.yaml``).

Holds non-secret operations settings (e.g. the Gmail connection provider and
write posture). Secrets (tokens, OAuth credentials, API keys) come from the
environment only — never from this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from company_brain.config import CONFIG_DIR


def load_operations_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Return the parsed ``config/operations.yaml`` (empty dict if absent)."""
    path = (config_dir or CONFIG_DIR) / "operations.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}
