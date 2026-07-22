"""HR department config from ``config/hr.yaml`` + ``config/hr_seed.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from company_brain.config import CONFIG_DIR, _load_yaml

_DEFAULTS: dict[str, Any] = {
    "archive_delay_days": 30,
    "timezone": "America/Los_Angeles",
    "linkedin": {"run_day": 1, "run_hour": 9, "run_minute": 0},
    "manager": {"poll_interval_minutes": 60},
    "slack": {"hr_channel": ""},
}


class HrSeedPerson(BaseModel):
    key: str
    email: str = ""
    employment_type: str = "w2"
    department: str = ""
    linkedin_url: str = ""
    start_date: str = ""
    end_date: str = ""
    role: str = "member"
    slack_user_id: str = ""
    notes: str = ""


class HrSeedConfig(BaseModel):
    current_employees: list[HrSeedPerson] = Field(default_factory=list)
    past_hires: list[HrSeedPerson] = Field(default_factory=list)


def _raw() -> dict[str, Any]:
    path = CONFIG_DIR / "hr.yaml"
    data = _load_yaml(path) if path.exists() else {}
    if not isinstance(data, dict):
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    for key, val in data.items():
        if key in ("linkedin", "manager", "slack") and isinstance(val, dict):
            block = dict(merged.get(key) or {})
            block.update(val)
            merged[key] = block
        elif val is not None:
            merged[key] = val
    return merged


def archive_delay_days() -> int:
    try:
        return max(1, int(_raw().get("archive_delay_days") or 30))
    except (TypeError, ValueError):
        return 30


def timezone_name() -> str:
    return str(_raw().get("timezone") or "America/Los_Angeles")


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name())
    except Exception:
        return ZoneInfo("America/Los_Angeles")


def linkedin_run_day() -> int:
    try:
        day = int((_raw().get("linkedin") or {}).get("run_day") or 1)
        return max(1, min(28, day))
    except (TypeError, ValueError):
        return 1


def linkedin_run_hour() -> int:
    try:
        return max(0, min(23, int((_raw().get("linkedin") or {}).get("run_hour") or 9)))
    except (TypeError, ValueError):
        return 9


def linkedin_run_minute() -> int:
    try:
        return max(0, min(59, int((_raw().get("linkedin") or {}).get("run_minute") or 0)))
    except (TypeError, ValueError):
        return 0


def poll_interval_minutes() -> int:
    try:
        return max(5, int((_raw().get("manager") or {}).get("poll_interval_minutes") or 60))
    except (TypeError, ValueError):
        return 60


def hr_channel() -> str:
    return str((_raw().get("slack") or {}).get("hr_channel") or "").strip()


def load_hr_seed(config_dir: Path | None = None) -> HrSeedConfig:
    path = (config_dir or CONFIG_DIR) / "hr_seed.yaml"
    data = _load_yaml(path) if path.exists() else {}
    if not isinstance(data, dict):
        return HrSeedConfig()
    return HrSeedConfig(**data)
