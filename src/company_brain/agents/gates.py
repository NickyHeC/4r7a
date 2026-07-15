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

    def delete(self, key: str) -> None:
        data = self._load()
        if key in data:
            del data[key]
            self._save(data)

    def keys(self, *, prefix: str = "") -> list[str]:
        """Return stored keys, optionally filtered by prefix."""
        return [k for k in self._load() if k.startswith(prefix)]


def changed_since(
    key: str, signature: Any, *, store: StateStore | None = None, update: bool = True
) -> bool:
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


# Renamed with the 2026-06 agent filename pass (``migrate-names --gate-keys``).
HANDLED_KEY_RENAMES: dict[str, str] = {
    "granola_ingest": "ingest",
    "granola_miss_check": "miss_check",
}

STATE_KEY_PREFIX_RENAMES: dict[str, str] = {
    "notion_task_scanner:last_scan:": "task_scanner:last_scan:",
}


def migrate_gate_keys(*, store: StateStore | None = None) -> dict[str, int]:
    """Rename ``config/state.json`` keys after agent renames. Returns counts."""
    store = store or StateStore()
    data = store._load()
    if not data:
        return {"handled": 0, "state": 0}

    handled = 0
    state = 0
    updated: dict[str, Any] = {}

    for key, value in data.items():
        new_key = key
        if key.startswith("handled:"):
            bare = key.removeprefix("handled:")
            if bare in HANDLED_KEY_RENAMES:
                new_key = f"handled:{HANDLED_KEY_RENAMES[bare]}"
                handled += 1
        else:
            for old_prefix, new_prefix in STATE_KEY_PREFIX_RENAMES.items():
                if key.startswith(old_prefix):
                    new_key = new_prefix + key[len(old_prefix) :]
                    state += 1
                    break
        if new_key in updated and updated[new_key] != value:
            logger.warning("Gate key migration collision: %s and %s", new_key, key)
        updated[new_key] = value

    if handled or state:
        store._save(updated)
    return {"handled": handled, "state": state}
