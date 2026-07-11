"""Roster index loaded from ``config/roster.yaml``.

Trial/intern/contractor roster — not W2 ``members.yaml``. Roster users cannot
invoke ``@weave``; promotion moves them into ``members.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from company_brain.config import CONFIG_DIR, _load_yaml
from company_brain.members_config import (
    MemberBindings,
    MemberSpec,
    load_members_config,
)

ROSTER_FILE = CONFIG_DIR / "roster.yaml"


class RosterPerson(BaseModel):
    email: str = ""
    employment_type: str = "contractor"
    slack_user_id: str = ""
    bindings: dict[str, Any] = Field(default_factory=dict)
    ingest: dict[str, Any] = Field(default_factory=dict)


class RosterConfig(BaseModel):
    people: dict[str, RosterPerson] = Field(default_factory=dict)

    def get(self, key: str) -> RosterPerson | None:
        return self.people.get(key)

    def find_by_slack_user_id(self, slack_user_id: str) -> str | None:
        ref = (slack_user_id or "").strip()
        if not ref:
            return None
        for key, person in self.people.items():
            if person.slack_user_id == ref:
                return key
        return None


def load_roster_config(config_dir: Path | None = None) -> RosterConfig:
    path = (config_dir or CONFIG_DIR) / "roster.yaml"
    data = _load_yaml(path)
    return RosterConfig(**data)


def save_roster_config(cfg: RosterConfig, config_dir: Path | None = None) -> None:
    path = (config_dir or CONFIG_DIR) / "roster.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"people": {k: v.model_dump() for k, v in cfg.people.items()}}
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False))
    tmp.replace(path)


def promote_roster_to_member(
    roster_key: str,
    *,
    member_key: str | None = None,
    role: str = "member",
) -> str:
    """Move a roster person into ``members.yaml`` and remove from roster."""
    roster = load_roster_config()
    person = roster.people.get(roster_key)
    if person is None:
        raise KeyError(f"roster key not found: {roster_key}")

    key = (member_key or roster_key).strip()
    members = load_members_config()
    if key in members.members:
        raise ValueError(f"member already exists: {key}")

    bindings = MemberBindings(
        slack_user_id=person.slack_user_id,
        gmail_mailbox=str(person.bindings.get("gmail_mailbox") or person.email),
        linear_user_id=str(person.bindings.get("linear_user_id") or ""),
        granola_label=str(person.bindings.get("granola_label") or key),
    )
    members.members[key] = MemberSpec(
        email=person.email,
        role=role,
        status="active",
        bindings=bindings,
    )

    members_path = CONFIG_DIR / "members.yaml"
    tmp = members_path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(
            {"members": {k: v.model_dump() for k, v in members.members.items()}},
            default_flow_style=False,
            sort_keys=False,
        )
    )
    tmp.replace(members_path)

    del roster.people[roster_key]
    save_roster_config(roster)
    return key
