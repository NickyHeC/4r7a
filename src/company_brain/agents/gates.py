"""Cost gates: cheap ($0) change-detection so agents skip work when nothing changed.

Two complementary mechanisms, both inspired by Ramp's self-maintaining system:

- ``StateStore`` + ``changed_since`` — compare a cheap signature (last commit
  SHA, last transaction id, max entry timestamp, ...) against a stored marker.
  If unchanged, the agent's ``should_run`` returns False and no LLM is invoked.
- ``mark_handled`` / ``is_handled`` — record "handled" state on the artifact
  itself (Ramp's "store state on the monitor" dedup) so a re-fire for an
  already-handled item stands down instead of re-acting.

State lives in ``config/state.json`` (a small fleet-shared marker store).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR

logger = logging.getLogger(__name__)

STATE_FILE = "state.json"


class StateStore:
    """Tiny JSON key/value store for gate markers."""

    def __init__(self, path: Path | None = None):
        self._path = path or (CONFIG_DIR / STATE_FILE)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text()) or {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def get(self, key: str) -> Any:
        return self._load().get(key)

    def set(self, key: str, value: Any) -> None:
        data = self._load()
        data[key] = value
        self._save(data)


def changed_since(key: str, signature: Any, *, store: StateStore | None = None,
                  update: bool = True) -> bool:
    """Return True if ``signature`` differs from the stored marker for ``key``.

    When True and ``update`` is set, the marker is advanced to ``signature`` so
    the next run sees the new baseline. ``signature`` should be cheap to compute
    (a count, max id/timestamp, hash) - never an LLM call.
    """
    store = store or StateStore()
    previous = store.get(key)
    if previous == signature:
        return False
    if update:
        store.set(key, signature)
    return True


def is_handled(key: str, signature: Any, *, store: StateStore | None = None) -> bool:
    """Return True if ``signature`` was already handled for ``key`` (dedup)."""
    store = store or StateStore()
    return store.get(f"handled:{key}") == signature


def mark_handled(key: str, signature: Any, *, store: StateStore | None = None) -> None:
    """Record that ``signature`` has been handled for ``key`` (stand down on re-fire)."""
    store = store or StateStore()
    store.set(f"handled:{key}", signature)
