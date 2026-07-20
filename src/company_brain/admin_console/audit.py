"""Append-only admin console audit ledger (gitignored)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR

LEDGER_NAME = "admin_console_events.jsonl"


def ledger_path() -> Path:
    return CONFIG_DIR / LEDGER_NAME


def append_event(kind: str, **fields: Any) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **fields,
    }
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
