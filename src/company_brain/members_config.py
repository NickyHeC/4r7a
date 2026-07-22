"""Member index loaded from ``config/members.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from company_brain.config import CONFIG_DIR, _load_yaml


class MemberBindings(BaseModel):
    granola_label: str = ""
    gmail_mailbox: str = ""
    slack_user_id: str = ""
    discord_id: str = ""
    discord_handle: str = ""
    linear_user_id: str = ""
    linkedin_url: str = ""


class MemberIngestConfig(BaseModel):
    granola: str = "full"
    gmail: str = "work_related"
    slack: str = "watched_channels_only"


class MemberBridgeConfig(BaseModel):
    departments: list[str] = Field(default_factory=list)


class MemberSpec(BaseModel):
    email: str = ""
    role: str = "member"
    status: str = "active"
    department: str = ""
    departed_at: str = ""
    wiki_archived: bool = False
    notion_teamspace: str = ""
    bridge: MemberBridgeConfig = Field(default_factory=MemberBridgeConfig)
    bindings: MemberBindings = Field(default_factory=MemberBindings)
    ingest: MemberIngestConfig = Field(default_factory=MemberIngestConfig)
    query_grants: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return (self.status or "active").strip().lower() == "active"

    @property
    def is_admin(self) -> bool:
        return (self.role or "member").strip().lower() == "admin"

    def employee_wiki_rel(self, member_key: str) -> str:
        """Relative path prefix under the employee wiki root (``{member}/``)."""
        return f"{member_key.strip()}/"


class MembersConfig(BaseModel):
    members: dict[str, MemberSpec] = Field(default_factory=dict)

    def get(self, member_key: str) -> MemberSpec | None:
        return self.members.get(member_key)

    def active_members(self) -> dict[str, MemberSpec]:
        return {k: v for k, v in self.members.items() if v.is_active}

    def find_by_linear_user(self, linear_user_id: str) -> str | None:
        ref = (linear_user_id or "").strip()
        if not ref:
            return None
        for key, spec in self.members.items():
            if spec.bindings.linear_user_id == ref:
                return key
        return None

    def find_by_granola_label(self, label: str) -> str | None:
        ref = (label or "").strip()
        if not ref:
            return None
        for key, spec in self.members.items():
            if spec.bindings.granola_label == ref:
                return key
        return None

    def find_by_gmail_mailbox(self, mailbox: str) -> str | None:
        ref = (mailbox or "").strip().lower()
        if not ref:
            return None
        for key, spec in self.members.items():
            if spec.bindings.gmail_mailbox.lower() == ref or spec.email.lower() == ref:
                return key
        return None

    def find_by_slack_user_id(self, slack_user_id: str) -> str | None:
        ref = (slack_user_id or "").strip()
        if not ref:
            return None
        for key, spec in self.members.items():
            if spec.bindings.slack_user_id == ref:
                return key
        return None

    def find_by_discord_id(self, discord_id: str) -> str | None:
        ref = (discord_id or "").strip()
        if not ref:
            return None
        for key, spec in self.members.items():
            if spec.bindings.discord_id == ref:
                return key
        return None

    def team_discord_ids(self) -> set[str]:
        ids: set[str] = set()
        for spec in self.active_members().values():
            ref = (spec.bindings.discord_id or "").strip()
            if ref:
                ids.add(ref)
        return ids


def resolve_member_for_binding(binding: Any, cfg: MembersConfig | None = None) -> str | None:
    """Best-effort member key from a task binding's origin platform."""
    cfg = cfg or load_members_config()
    origin = str(getattr(binding, "origin", {}).get("platform") or "")
    platforms = getattr(binding, "platforms", {}) or {}

    if origin == "gmail":
        mailbox = (platforms.get("gmail") or {}).get("mailbox") or ""
        return cfg.find_by_gmail_mailbox(str(mailbox))
    if origin == "granola":
        note_id = str((platforms.get("granola") or {}).get("note_id") or "")
        for key, spec in cfg.members.items():
            label = spec.bindings.granola_label
            if label and label in note_id:
                return key
    if origin == "slack":
        channel = (platforms.get("slack") or {}).get("channel") or ""
        for key, spec in cfg.members.items():
            if spec.bindings.slack_user_id and spec.bindings.slack_user_id in channel:
                return key
    return None


def load_members_config(config_dir: Path | None = None) -> MembersConfig:
    path = (config_dir or CONFIG_DIR) / "members.yaml"
    data = _load_yaml(path)
    return MembersConfig(**data)


def save_members_config(cfg: MembersConfig, config_dir: Path | None = None) -> None:
    path = (config_dir or CONFIG_DIR) / "members.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"members": {k: v.model_dump() for k, v in cfg.members.items()}}
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False))
    tmp.replace(path)


def update_member(
    member_key: str,
    *,
    config_dir: Path | None = None,
    **fields: Any,
) -> MemberSpec:
    """Patch fields on a member and persist. Raises KeyError if missing."""
    cfg = load_members_config(config_dir)
    spec = cfg.members.get(member_key)
    if spec is None:
        raise KeyError(f"member not found: {member_key}")
    data = spec.model_dump()
    for key, val in fields.items():
        if key == "bindings" and isinstance(val, dict):
            merged = dict(data.get("bindings") or {})
            merged.update(val)
            data["bindings"] = merged
        elif key == "bridge" and isinstance(val, dict):
            merged = dict(data.get("bridge") or {})
            merged.update(val)
            data["bridge"] = merged
        elif key == "ingest" and isinstance(val, dict):
            merged = dict(data.get("ingest") or {})
            merged.update(val)
            data["ingest"] = merged
        else:
            data[key] = val
    cfg.members[member_key] = MemberSpec(**data)
    save_members_config(cfg, config_dir)
    return cfg.members[member_key]
