"""Member index loaded from ``config/members.yaml``."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from typing import Any

from company_brain.config import CONFIG_DIR, _load_yaml


class MemberBindings(BaseModel):
    granola_label: str = ""
    gmail_mailbox: str = ""
    slack_user_id: str = ""
    linear_user_id: str = ""


class MemberIngestConfig(BaseModel):
    granola: str = "full"
    gmail: str = "work_related"
    slack: str = "watched_channels_only"


class MemberSpec(BaseModel):
    email: str = ""
    status: str = "active"
    notion_teamspace: str = ""
    bindings: MemberBindings = Field(default_factory=MemberBindings)
    ingest: MemberIngestConfig = Field(default_factory=MemberIngestConfig)
    query_grants: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return (self.status or "active").strip().lower() == "active"

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
