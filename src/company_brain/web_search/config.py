"""Load ``config/web_search.yaml`` — default search backend for agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR, _load_yaml

_DEFAULTS: dict[str, Any] = {
    "backend": "auto",
    "lsearch": {
        "binary": "lsearch",
        "engine": "google",
        "limit": 5,
        "timeout_seconds": 90,
        "with_content": False,
        "content_chars": 1200,
        "cleanup_after": True,
    },
}


def _raw(config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or CONFIG_DIR) / "web_search.yaml"
    data = _load_yaml(path) if path.exists() else {}
    if not isinstance(data, dict):
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    for key, val in data.items():
        if key == "lsearch" and isinstance(val, dict):
            block = dict(merged.get("lsearch") or {})
            block.update({k: v for k, v in val.items() if v is not None})
            merged["lsearch"] = block
        elif val is not None:
            merged[key] = val
    return merged


def configured_backend(config_dir: Path | None = None) -> str:
    raw = str(_raw(config_dir).get("backend") or "auto").strip().lower()
    if raw in {"auto", "lsearch", "claude"}:
        return raw
    return "auto"


def lsearch_settings(config_dir: Path | None = None) -> dict[str, Any]:
    return dict(_raw(config_dir).get("lsearch") or {})
