"""Doctor scoring and history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "doctor-history.json"
BASELINE_FILE = CONFIG_DIR / "doctor-baseline.json"


def compute_score(fail_rules: set[str], warn_rules: set[str]) -> int:
    """Score on unique rules: 100 − 1.5×fails − 0.75×warns, clamped [0, 100]."""
    raw = 100.0 - 1.5 * len(fail_rules) - 0.75 * len(warn_rules)
    return max(0, min(100, int(round(raw))))


def append_history(entry: dict[str, Any], path: Path | None = None) -> None:
    path = path or HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data: list[dict[str, Any]] = []
    if path.exists():
        try:
            data = json.loads(path.read_text()) or []
        except (OSError, json.JSONDecodeError):
            data = []
    data.append(entry)
    if len(data) > 200:
        data = data[-200:]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def load_baseline(path: Path | None = None) -> dict[str, set[str]]:
    path = path or BASELINE_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text()) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, set[str]] = {}
    for name, body in raw.items():
        if isinstance(body, dict):
            out[name] = set(body.get("fail_rules") or [])
    return out


def save_baseline(reports: dict[str, Any], path: Path | None = None) -> None:
    path = path or BASELINE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        name: {"fail_rules": sorted(report.fail_rules)}
        for name, report in reports.items()
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


def new_fail_regressions(
    reports: dict[str, Any],
    baseline: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    """Fail rules present now but not in baseline (for CI diff gating)."""
    baseline = baseline if baseline is not None else load_baseline()
    regressions: dict[str, set[str]] = {}
    for name, report in reports.items():
        known = baseline.get(name, set())
        added = report.fail_rules - known
        if added:
            regressions[name] = added
    return regressions


def history_entry(reports: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "doctors": {name: report.to_dict() for name, report in reports.items()},
        "aggregate_score": min(r.score for r in reports.values()) if reports else 100,
    }
